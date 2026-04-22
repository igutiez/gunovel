"""Bucle de tool use contra la API de Anthropic.

Responsabilidades:
- Llamar a la API con system + messages + tools, con cache_control en bloques estables.
- Ejecutar herramientas de solo lectura inmediatamente.
- Cortar tras `MAX_TOOL_CALLS_POR_TURNO` ejecuciones.
- Devolver texto final + registro de tool calls para persistir en audit.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from ..config import Config
from ..files.project import Proyecto
from . import propuestas as prop_mod
from .context_builder import (
    contexto_capa1,
    contexto_capa2,
    contexto_capa3,
    serializar_capa_como_texto,
)
from .pricing import calcular_coste_eur
from .prompts import componer_system_prompt
from .tools import TOOL_SCHEMAS, ToolError, ejecutar_tool


log = logging.getLogger("novela_app.ai")


@dataclass
class TurnoResultado:
    texto_final: str
    tool_calls: list[dict] = field(default_factory=list)
    propuestas: list[dict] = field(default_factory=list)
    tokens_input: int = 0
    tokens_cache_read: int = 0
    tokens_cache_write: int = 0
    tokens_output: int = 0
    coste_eur: float = 0.0
    truncado_por_limite: bool = False
    error: str | None = None


def _cliente_anthropic():
    """Importa anthropic con mensaje de error claro si falta API key."""
    if not Config.ANTHROPIC_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY no configurada. Añádela al .env para usar el chat IA."
        )
    from anthropic import Anthropic

    return Anthropic(api_key=Config.ANTHROPIC_API_KEY)


def _construir_bloques_sistema(proyecto: Proyecto, ruta_activa: str | None) -> list[dict]:
    """Construye el `system` como lista de bloques con cache_control selectivo."""
    capa1 = contexto_capa1(proyecto)
    system_text = componer_system_prompt(
        nombre_proyecto=proyecto.nombre,
        estilo=capa1.get("estilo"),
        personajes_resumen=capa1.get("personajes_resumen"),
        estructura=capa1.get("actos"),
    )

    # Añadimos premisa/tesis/sinopsis detrás del system prompt como bloque
    # estable separado (también cacheado).
    extras: list[str] = []
    if capa1.get("premisa"):
        extras.append(f"## Premisa\n{capa1['premisa']}")
    if capa1.get("tesis"):
        extras.append(f"## Tesis\n{capa1['tesis']}")
    if capa1.get("sinopsis"):
        extras.append(f"## Sinopsis\n{capa1['sinopsis']}")

    # Capa 1: cache TTL 1h (amortiza cuando hay varias conversaciones en la sesión).
    bloques: list[dict] = [
        {
            "type": "text",
            "text": system_text,
            "cache_control": {"type": "ephemeral", "ttl": "1h"},
        }
    ]
    if extras:
        bloques.append(
            {
                "type": "text",
                "text": "\n\n".join(extras),
                "cache_control": {"type": "ephemeral", "ttl": "1h"},
            }
        )

    # Capa 2 (semi-estable)
    capa2 = contexto_capa2(proyecto, ruta_activa)
    texto_capa2 = serializar_capa_como_texto("Contexto del fichero activo", capa2)
    if texto_capa2:
        bloques.append(
            {
                "type": "text",
                "text": texto_capa2,
                "cache_control": {"type": "ephemeral"},
            }
        )

    # Capa 3 (variable): va dentro del turno del usuario, no como system.
    return bloques


def _construir_primer_mensaje_usuario(
    proyecto: Proyecto, ruta_activa: str | None, mensaje_usuario: str
) -> str:
    capa3 = contexto_capa3(proyecto, ruta_activa)
    partes: list[str] = []
    if capa3:
        partes.append("## Fichero activo")
        partes.append(f"Ruta: {capa3.get('fichero_activo_ruta')}")
        if capa3.get("fichero_activo_titulo"):
            partes.append(f"Título: {capa3['fichero_activo_titulo']}")
        meta = capa3.get("fichero_activo_metadata")
        if meta:
            partes.append(f"Metadata: {json.dumps(meta, ensure_ascii=False)}")
        partes.append("\nContenido actual:")
        partes.append("```markdown")
        partes.append(capa3.get("fichero_activo_content") or "")
        partes.append("```")
        partes.append("")

    partes.append("## Instrucción del usuario")
    partes.append(mensaje_usuario.strip())
    return "\n".join(partes)


def ejecutar_turno(
    proyecto: Proyecto,
    ruta_activa: str | None,
    historial: list[dict],
    mensaje_usuario: str,
    conversacion_id: str | None = None,
    modelo: str | None = None,
) -> TurnoResultado:
    """Ejecuta un turno completo del chat con bucle de tool use.

    `historial` son los mensajes previos ya en formato API (role, content).
    Se añade el turno nuevo dentro de esta función.
    """
    modelo = modelo or (proyecto.config.get("modelo_por_defecto") or Config.MODELO_POR_DEFECTO)

    resultado = TurnoResultado(texto_final="")

    try:
        cliente = _cliente_anthropic()
    except RuntimeError as exc:
        resultado.error = str(exc)
        return resultado

    bloques_sistema = _construir_bloques_sistema(proyecto, ruta_activa)

    primer_msg = _construir_primer_mensaje_usuario(proyecto, ruta_activa, mensaje_usuario)
    messages: list[dict] = list(historial) + [
        {"role": "user", "content": primer_msg}
    ]

    tool_calls_registrados: list[dict] = []

    for iteracion in range(Config.MAX_TOOL_CALLS_POR_TURNO + 1):
        resp = _llamar_api_con_retry(
            cliente,
            modelo=modelo,
            system=bloques_sistema,
            messages=messages,
        )
        if isinstance(resp, str):  # error message
            resultado.error = resp
            return resultado

        # Acumular uso
        usage = getattr(resp, "usage", None)
        if usage is not None:
            resultado.tokens_input += getattr(usage, "input_tokens", 0) or 0
            resultado.tokens_output += getattr(usage, "output_tokens", 0) or 0
            resultado.tokens_cache_read += getattr(usage, "cache_read_input_tokens", 0) or 0
            resultado.tokens_cache_write += getattr(usage, "cache_creation_input_tokens", 0) or 0

        # Recoger texto y tool_use
        content_blocks = resp.content or []
        texto_parcial = "".join(
            b.text for b in content_blocks if getattr(b, "type", None) == "text"
        )
        tool_uses = [b for b in content_blocks if getattr(b, "type", None) == "tool_use"]

        if resp.stop_reason != "tool_use" or not tool_uses:
            resultado.texto_final = texto_parcial
            break

        if iteracion >= Config.MAX_TOOL_CALLS_POR_TURNO:
            resultado.truncado_por_limite = True
            resultado.texto_final = (
                texto_parcial
                + "\n\n[Sistema: alcanzado límite de "
                + str(Config.MAX_TOOL_CALLS_POR_TURNO)
                + " herramientas en este turno. Resumo progreso y espero al usuario.]"
            )
            break

        # Añadir el assistant turn tal cual (bloques con tool_use)
        messages.append({"role": "assistant", "content": [_serializar_bloque(b) for b in content_blocks]})

        # Ejecutar las tools y preparar tool_result
        tool_results_payload: list[dict] = []
        for tu in tool_uses:
            nombre = tu.name
            args = tu.input or {}
            try:
                resultado_tool = ejecutar_tool(
                    nombre, args, proyecto, conversacion_id=conversacion_id
                )
                texto_result = json.dumps(resultado_tool, ensure_ascii=False)
                if len(texto_result) > Config.MAX_CHARS_TOOL_RESULT:
                    texto_result = (
                        texto_result[: Config.MAX_CHARS_TOOL_RESULT]
                        + f"\n\n[...truncado a {Config.MAX_CHARS_TOOL_RESULT} caracteres. "
                        "Pide una búsqueda más específica si necesitas el resto.]"
                    )
                is_error = False
            except ToolError as exc:
                texto_result = f"Error: {exc}"
                is_error = True
            except Exception as exc:  # noqa: BLE001
                log.exception("Error ejecutando tool %s", nombre)
                texto_result = f"Error interno ejecutando herramienta: {exc}"
                is_error = True

            tool_calls_registrados.append(
                {
                    "name": nombre,
                    "input": args,
                    "is_error": is_error,
                    "result_preview": texto_result[:500],
                }
            )

            tool_results_payload.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": texto_result,
                    "is_error": is_error,
                }
            )

        messages.append({"role": "user", "content": tool_results_payload})

    resultado.tool_calls = tool_calls_registrados
    if conversacion_id:
        resultado.propuestas = [
            prop_mod.serializar(p)
            for p in prop_mod.listar_pendientes_conversacion(conversacion_id)
        ]
    resultado.coste_eur = calcular_coste_eur(
        modelo=modelo,
        tokens_input=resultado.tokens_input,
        tokens_cache_read=resultado.tokens_cache_read,
        tokens_cache_write=resultado.tokens_cache_write,
        tokens_output=resultado.tokens_output,
    )
    return resultado


def _llamar_api_con_retry(cliente, *, modelo, system, messages):
    """Llamada con retry+backoff según spec 15.2.

    Rate limit (429): 3 reintentos con backoff 1s/2s/4s.
    Server error (5xx): 2 reintentos con backoff.
    Resto: falla inmediatamente.
    """
    from anthropic import APIStatusError, APIConnectionError, RateLimitError

    backoffs_429 = [1.0, 2.0, 4.0]
    backoffs_5xx = [1.0, 2.0]

    intento_429 = 0
    intento_5xx = 0
    while True:
        try:
            return cliente.messages.create(
                model=modelo,
                max_tokens=Config.MAX_TOKENS_OUTPUT,
                system=system,
                tools=TOOL_SCHEMAS,
                messages=messages,
            )
        except RateLimitError as exc:
            if intento_429 >= len(backoffs_429):
                log.warning("Rate limit tras %d reintentos", intento_429)
                return f"Rate limit persistente: {exc}"
            time.sleep(backoffs_429[intento_429])
            intento_429 += 1
        except APIStatusError as exc:
            code = getattr(exc, "status_code", 0) or 0
            if 500 <= code < 600:
                if intento_5xx >= len(backoffs_5xx):
                    return f"Error {code} persistente: {exc}"
                time.sleep(backoffs_5xx[intento_5xx])
                intento_5xx += 1
                continue
            return f"Error de la API ({code}): {exc}"
        except APIConnectionError as exc:
            if intento_5xx >= len(backoffs_5xx):
                return f"Sin conexión a la API: {exc}"
            time.sleep(backoffs_5xx[intento_5xx])
            intento_5xx += 1
        except Exception as exc:  # noqa: BLE001
            log.exception("Error llamando a Anthropic")
            return f"Error de la API: {exc}"


def _serializar_bloque(b: Any) -> dict:
    tipo = getattr(b, "type", None)
    if tipo == "text":
        return {"type": "text", "text": b.text}
    if tipo == "tool_use":
        return {
            "type": "tool_use",
            "id": b.id,
            "name": b.name,
            "input": b.input,
        }
    if tipo == "thinking":
        return {"type": "thinking", "thinking": getattr(b, "thinking", "")}
    # Desconocido: intentar model_dump si está disponible
    if hasattr(b, "model_dump"):
        return b.model_dump()
    return {"type": "unknown"}
