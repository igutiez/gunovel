"""Ejecuta UN paso del loop autónomo.

Cada paso:
1. Verifica frenos: presupuesto, cola de propuestas, stuck.
2. Arma el mensaje del orquestador (instrucción del turno) a partir del estado.
3. Llama a ejecutar_turno (bucle de tool use ya existente) con historial persistido.
4. Evalúa el resultado: propuestas nuevas, preguntas registradas, si terminó.
5. Actualiza estado de la ejecución.

El plan vive como fichero Markdown en el proyecto:
    05_control/plan_autonomo.md

El autor puede editarlo a mano entre pasos (la IA lo releerá cada turno).
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass

from ..ai import propuestas as prop_mod
from ..ai.tool_use import ejecutar_turno
from ..audit.db import acumular_coste_conversacion, añadir_mensaje, crear_conversacion, mensajes_de_conversacion
from ..config import Config
from ..files.project import Proyecto
from . import db as autodb
from .frenos import evaluar_frenos
from .prompts import construir_mensaje_orquestador


log = logging.getLogger("novela_app.autonomo")


@dataclass
class ResultadoPaso:
    ejecucion: dict
    mensaje_asistente: str
    propuestas_nuevas: int
    preguntas_nuevas: int
    coste_paso_eur: float
    pausar: bool
    razon_pausa: str | None


def ejecutar_paso(proyecto: Proyecto, ejecucion: dict) -> ResultadoPaso:
    eid = ejecucion["id"]

    # --- Freno 1: presupuesto ---
    if ejecucion["coste_acumulado_eur"] >= ejecucion["presupuesto_eur"]:
        autodb.actualizar_estado(
            eid,
            estado="error_presupuesto",
            razon_pausa=f"Coste {ejecucion['coste_acumulado_eur']:.2f} € >= presupuesto {ejecucion['presupuesto_eur']:.2f} €.",
        )
        return _pausa(ejecucion, "error_presupuesto", "Presupuesto agotado.")

    # --- Freno 2: preguntas pendientes ---
    pendientes = autodb.preguntas_de_ejecucion(eid, solo_nuevas=True)
    if pendientes:
        autodb.actualizar_estado(
            eid,
            estado="esperando_autor",
            razon_pausa=f"{len(pendientes)} pregunta(s) del autor sin responder.",
        )
        return _pausa(ejecucion, "esperando_autor", f"{len(pendientes)} pregunta(s) al autor pendientes.")

    # --- Freno 3: cola de propuestas llena ---
    pendientes_propuestas = prop_mod.listar_pendientes_proyecto(proyecto.slug)
    if len(pendientes_propuestas) >= ejecucion["max_propuestas_cola"]:
        autodb.actualizar_estado(
            eid,
            estado="esperando_revision",
            razon_pausa=f"Cola de propuestas en {len(pendientes_propuestas)} (tope {ejecucion['max_propuestas_cola']}).",
        )
        return _pausa(ejecucion, "esperando_revision", "Cola de propuestas llena; revisa antes de seguir.")

    # --- Conversación persistida ---
    conv_id = ejecucion["conversacion_id"]
    if not conv_id:
        conv_id = crear_conversacion(proyecto.slug, titulo=f"[Autónomo] {ejecucion['fase']}")
        with_conv_update = True
    else:
        with_conv_update = False

    # --- Mensaje del orquestador para este turno ---
    mensaje_turno = construir_mensaje_orquestador(proyecto, ejecucion)

    añadir_mensaje(conv_id, "user", mensaje_turno)

    historial = _historial_para_api(mensajes_de_conversacion(conv_id))

    resultado = ejecutar_turno(
        proyecto=proyecto,
        ruta_activa=None,
        historial=historial[:-1],  # sin el último que ya se incluirá como nuevo turno
        mensaje_usuario=mensaje_turno,
        conversacion_id=conv_id,
        modelo=ejecucion["modelo"],
    )

    if resultado.error:
        añadir_mensaje(conv_id, "assistant", f"[Error] {resultado.error}")
        autodb.actualizar_estado(
            eid,
            estado="pausado",
            razon_pausa=f"Error de API: {resultado.error}",
            incrementar_paso=True,
            firma_ultimas_tools=_firma(resultado.tool_calls or []),
        )
        return _pausa(ejecucion, "pausado", f"Error de API: {resultado.error}")

    añadir_mensaje(
        conv_id,
        "assistant",
        resultado.texto_final,
        tool_calls=resultado.tool_calls or None,
    )
    if resultado.coste_eur:
        acumular_coste_conversacion(conv_id, resultado.coste_eur)

    # --- Evaluar frenos post-turno ---
    frenos = evaluar_frenos(
        proyecto=proyecto,
        ejecucion=ejecucion,
        tool_calls=resultado.tool_calls or [],
        propuestas_nuevas_count=len(resultado.propuestas),
        coste_paso=resultado.coste_eur,
    )

    # Actualizar ejecución
    nuevos_updates = {
        "sumar_coste": resultado.coste_eur,
        "incrementar_paso": True,
        "firma_ultimas_tools": _firma(resultado.tool_calls or []),
    }

    preguntas_nuevas = len(autodb.preguntas_de_ejecucion(eid, solo_nuevas=True))

    if frenos.pausar:
        nuevos_updates["estado"] = frenos.estado
        nuevos_updates["razon_pausa"] = frenos.razon
    elif preguntas_nuevas > 0:
        nuevos_updates["estado"] = "esperando_autor"
        nuevos_updates["razon_pausa"] = f"{preguntas_nuevas} pregunta(s) registradas."
    elif _parece_terminado(resultado.texto_final):
        nuevos_updates["estado"] = "terminado"
        nuevos_updates["razon_pausa"] = "Orquestador indica que ha completado la fase."

    if with_conv_update or nuevos_updates.get("estado") == "terminado":
        with autodb._lock, autodb._conn() as c:  # type: ignore[attr-defined]
            if with_conv_update:
                c.execute(
                    "UPDATE ejecuciones_autonomo SET conversacion_id = ? WHERE id = ?",
                    (conv_id, eid),
                )
            if nuevos_updates.get("estado") == "terminado":
                c.execute(
                    "UPDATE ejecuciones_autonomo SET fin = ? WHERE id = ?",
                    (autodb._ahora(), eid),
                )

    autodb.actualizar_estado(eid, **nuevos_updates)

    ejecucion_actualizada = autodb.obtener_ejecucion(eid) or ejecucion
    return ResultadoPaso(
        ejecucion=ejecucion_actualizada,
        mensaje_asistente=resultado.texto_final,
        propuestas_nuevas=len(resultado.propuestas),
        preguntas_nuevas=preguntas_nuevas,
        coste_paso_eur=resultado.coste_eur,
        pausar=bool(frenos.pausar) or preguntas_nuevas > 0 or nuevos_updates.get("estado") in ("terminado",),
        razon_pausa=nuevos_updates.get("razon_pausa"),
    )


def _pausa(ejecucion: dict, estado: str, razon: str) -> ResultadoPaso:
    actualizada = autodb.obtener_ejecucion(ejecucion["id"]) or ejecucion
    return ResultadoPaso(
        ejecucion=actualizada,
        mensaje_asistente="",
        propuestas_nuevas=0,
        preguntas_nuevas=0,
        coste_paso_eur=0.0,
        pausar=True,
        razon_pausa=razon,
    )


def _firma(tool_calls: list[dict]) -> str:
    if not tool_calls:
        return ""
    clave = "|".join(f"{t.get('name')}:{json.dumps(t.get('input') or {}, sort_keys=True)}" for t in tool_calls)
    return hashlib.sha256(clave.encode("utf-8")).hexdigest()[:16]


def _parece_terminado(texto: str) -> bool:
    if not texto:
        return False
    # El prompt orquestador indica que escriba exactamente esta línea si ha acabado:
    return "[FASE_COMPLETADA]" in texto or "[AUTONOMO_TERMINADO]" in texto


def _historial_para_api(mensajes: list[dict]) -> list[dict]:
    out: list[dict] = []
    for m in mensajes:
        if m["rol"] not in ("user", "assistant"):
            continue
        if not m["contenido"]:
            continue
        out.append({"role": m["rol"], "content": m["contenido"]})
    return out[-Config.VENTANA_HISTORIAL_MENSAJES:]
