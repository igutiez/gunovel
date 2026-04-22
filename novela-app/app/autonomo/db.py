"""CRUD para ejecuciones autónomas y preguntas al autor."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from ..audit.db import _conn, _lock


ESTADOS = {"ejecutando", "pausado", "esperando_autor", "esperando_revision", "detenido", "terminado", "error_presupuesto", "error_stuck"}


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Ejecuciones
# ---------------------------------------------------------------------------

def crear_ejecucion(
    *,
    proyecto_slug: str,
    fase: str,
    modelo: str,
    presupuesto_eur: float,
    conversacion_id: str | None = None,
    golden_reference_ruta: str | None = None,
    max_propuestas_cola: int = 20,
) -> str:
    eid = str(uuid.uuid4())
    with _lock, _conn() as c:
        c.execute(
            """
            INSERT INTO ejecuciones_autonomo (
                id, proyecto_slug, estado, fase, modelo, presupuesto_eur,
                coste_acumulado_eur, inicio, conversacion_id,
                golden_reference_ruta, max_propuestas_cola, pasos_ejecutados,
                ultima_actividad
            ) VALUES (?, ?, 'ejecutando', ?, ?, ?, 0, ?, ?, ?, ?, 0, ?)
            """,
            (
                eid,
                proyecto_slug,
                fase,
                modelo,
                presupuesto_eur,
                _ahora(),
                conversacion_id,
                golden_reference_ruta,
                max_propuestas_cola,
                _ahora(),
            ),
        )
    return eid


def obtener_ejecucion(ejecucion_id: str) -> dict | None:
    with _lock, _conn() as c:
        r = c.execute(
            "SELECT * FROM ejecuciones_autonomo WHERE id = ?",
            (ejecucion_id,),
        ).fetchone()
    return dict(r) if r else None


def ejecucion_activa_de_proyecto(proyecto_slug: str) -> dict | None:
    with _lock, _conn() as c:
        r = c.execute(
            """
            SELECT * FROM ejecuciones_autonomo
            WHERE proyecto_slug = ?
              AND estado IN ('ejecutando','pausado','esperando_autor','esperando_revision')
            ORDER BY inicio DESC LIMIT 1
            """,
            (proyecto_slug,),
        ).fetchone()
    return dict(r) if r else None


def actualizar_estado(
    ejecucion_id: str,
    *,
    estado: str | None = None,
    razon_pausa: str | None = None,
    incrementar_paso: bool = False,
    sumar_coste: float | None = None,
    firma_ultimas_tools: str | None = None,
    marcar_fin: bool = False,
) -> None:
    partes: list[str] = []
    args: list = []
    if estado is not None:
        partes.append("estado = ?")
        args.append(estado)
    if razon_pausa is not None:
        partes.append("razon_pausa = ?")
        args.append(razon_pausa)
    if incrementar_paso:
        partes.append("pasos_ejecutados = pasos_ejecutados + 1")
    if sumar_coste is not None:
        partes.append("coste_acumulado_eur = coste_acumulado_eur + ?")
        args.append(sumar_coste)
    if firma_ultimas_tools is not None:
        partes.append("firma_ultimas_tools = ?")
        args.append(firma_ultimas_tools)
    if marcar_fin:
        partes.append("fin = ?")
        args.append(_ahora())
    partes.append("ultima_actividad = ?")
    args.append(_ahora())

    args.append(ejecucion_id)
    sql = f"UPDATE ejecuciones_autonomo SET {', '.join(partes)} WHERE id = ?"
    with _lock, _conn() as c:
        c.execute(sql, args)


# ---------------------------------------------------------------------------
# Preguntas al autor
# ---------------------------------------------------------------------------

def registrar_pregunta(
    *,
    ejecucion_id: str,
    proyecto_slug: str,
    pregunta: str,
    contexto: str = "",
    prioridad: str = "normal",
) -> str:
    pid = str(uuid.uuid4())
    with _lock, _conn() as c:
        c.execute(
            """
            INSERT INTO preguntas_autor (
                id, ejecucion_id, proyecto_slug, timestamp, pregunta,
                contexto, prioridad
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (pid, ejecucion_id, proyecto_slug, _ahora(), pregunta, contexto, prioridad),
        )
    return pid


def preguntas_pendientes(proyecto_slug: str) -> list[dict]:
    with _lock, _conn() as c:
        rows = c.execute(
            """
            SELECT * FROM preguntas_autor
            WHERE proyecto_slug = ? AND respuesta IS NULL
            ORDER BY timestamp ASC
            """,
            (proyecto_slug,),
        ).fetchall()
    return [dict(r) for r in rows]


def preguntas_de_ejecucion(ejecucion_id: str, solo_nuevas: bool = False) -> list[dict]:
    with _lock, _conn() as c:
        if solo_nuevas:
            rows = c.execute(
                """
                SELECT * FROM preguntas_autor
                WHERE ejecucion_id = ? AND respuesta IS NULL
                ORDER BY timestamp ASC
                """,
                (ejecucion_id,),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM preguntas_autor WHERE ejecucion_id = ? ORDER BY timestamp ASC",
                (ejecucion_id,),
            ).fetchall()
    return [dict(r) for r in rows]


def responder_pregunta(pregunta_id: str, respuesta: str) -> None:
    with _lock, _conn() as c:
        c.execute(
            "UPDATE preguntas_autor SET respuesta = ?, respondida_en = ? WHERE id = ?",
            (respuesta, _ahora(), pregunta_id),
        )


def obtener_pregunta(pregunta_id: str) -> dict | None:
    with _lock, _conn() as c:
        r = c.execute(
            "SELECT * FROM preguntas_autor WHERE id = ?",
            (pregunta_id,),
        ).fetchone()
    return dict(r) if r else None
