"""Resumir mensajes antiguos con Haiku para no explotar la ventana."""
from __future__ import annotations

import logging

from ..config import Config


log = logging.getLogger("novela_app.ai.resumen")


PROMPT_RESUMEN = (
    "Resume la conversación anterior entre autor y asistente editorial en un solo "
    "bloque compacto (máximo 250 palabras). Mantén:\n"
    "- Decisiones narrativas tomadas.\n"
    "- Ficheros tocados o propuestas aplicadas.\n"
    "- Cuestiones abiertas.\n"
    "No inventes. No repitas el contenido literal de capítulos. Si no hay decisiones, "
    "devuelve 'Sin decisiones relevantes aún.'"
)


def resumir_historial(mensajes: list[dict]) -> str:
    """Llama a Haiku con los mensajes antiguos y devuelve un resumen de una cadena.

    Si la API no está configurada o falla, devuelve un resumen trivial.
    """
    if not Config.ANTHROPIC_API_KEY:
        return _resumen_trivial(mensajes)
    try:
        from anthropic import Anthropic

        cliente = Anthropic(api_key=Config.ANTHROPIC_API_KEY)
        texto_conversacion = "\n\n".join(
            f"[{m['role'].upper()}] {m['content'][:1200]}" for m in mensajes
        )
        resp = cliente.messages.create(
            model=Config.MODELO_HAIKU,
            max_tokens=512,
            system=PROMPT_RESUMEN,
            messages=[{"role": "user", "content": texto_conversacion}],
        )
        partes = [b.text for b in (resp.content or []) if getattr(b, "type", None) == "text"]
        return ("\n".join(partes)).strip() or _resumen_trivial(mensajes)
    except Exception:
        log.exception("Error resumiendo historial con Haiku")
        return _resumen_trivial(mensajes)


def _resumen_trivial(mensajes: list[dict]) -> str:
    lineas = []
    for m in mensajes[:20]:
        rol = m["role"].upper()
        contenido = (m["content"] or "").replace("\n", " ")[:120]
        lineas.append(f"- [{rol}] {contenido}")
    return "Resumen automático (sin IA):\n" + "\n".join(lineas)
