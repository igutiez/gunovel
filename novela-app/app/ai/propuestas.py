"""Cola de propuestas de escritura pendientes de aprobación.

Persistidas en SQLite (tabla `propuestas`). Sobreviven a reinicios del server.
"""
from __future__ import annotations

import difflib
import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from ..audit.db import _conn, _lock


TipoPropuesta = Literal[
    "modificar_fichero",
    "crear_fichero",
    "reordenar_capitulos",
    "actualizar_grafo_relaciones",
]


@dataclass
class Propuesta:
    id: str
    tipo: TipoPropuesta
    proyecto_slug: str
    conversacion_id: str | None
    motivo: str
    ruta: str | None = None
    contenido_nuevo: str | None = None
    contenido_anterior: str | None = None
    nuevo_orden: list[str] | None = None
    orden_anterior: list[str] | None = None
    cambios: list[dict] | None = None
    creado: float = 0.0
    estado: Literal["pendiente", "aplicada", "rechazada"] = "pendiente"


def _ahora_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_a_propuesta(r: sqlite3.Row) -> Propuesta:
    return Propuesta(
        id=r["id"],
        tipo=r["tipo"],
        proyecto_slug=r["proyecto_slug"],
        conversacion_id=r["conversacion_id"],
        motivo=r["motivo"],
        ruta=r["ruta"],
        contenido_nuevo=r["contenido_nuevo"],
        contenido_anterior=r["contenido_anterior"],
        nuevo_orden=json.loads(r["nuevo_orden_json"]) if r["nuevo_orden_json"] else None,
        orden_anterior=json.loads(r["orden_anterior_json"]) if r["orden_anterior_json"] else None,
        cambios=json.loads(r["cambios_json"]) if r["cambios_json"] else None,
        creado=_parse_creado(r["creado"]),
        estado=r["estado"],
    )


def _parse_creado(s: str) -> float:
    try:
        return datetime.fromisoformat(s).timestamp()
    except (ValueError, TypeError):
        return time.time()


def registrar(p: Propuesta) -> None:
    with _lock, _conn() as c:
        c.execute(
            """
            INSERT INTO propuestas (
                id, tipo, proyecto_slug, conversacion_id, motivo,
                ruta, contenido_nuevo, contenido_anterior,
                nuevo_orden_json, orden_anterior_json, cambios_json,
                creado, estado
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                p.id,
                p.tipo,
                p.proyecto_slug,
                p.conversacion_id,
                p.motivo,
                p.ruta,
                p.contenido_nuevo,
                p.contenido_anterior,
                json.dumps(p.nuevo_orden) if p.nuevo_orden is not None else None,
                json.dumps(p.orden_anterior) if p.orden_anterior is not None else None,
                json.dumps(p.cambios) if p.cambios is not None else None,
                _ahora_iso(),
                p.estado,
            ),
        )


def obtener(propuesta_id: str) -> Propuesta | None:
    with _lock, _conn() as c:
        r = c.execute("SELECT * FROM propuestas WHERE id = ?", (propuesta_id,)).fetchone()
    return _row_a_propuesta(r) if r else None


def marcar(propuesta_id: str, estado: Literal["aplicada", "rechazada"]) -> None:
    with _lock, _conn() as c:
        c.execute("UPDATE propuestas SET estado = ? WHERE id = ?", (estado, propuesta_id))


def actualizar_contenido(propuesta_id: str, contenido_nuevo: str) -> None:
    with _lock, _conn() as c:
        c.execute(
            "UPDATE propuestas SET contenido_nuevo = ? WHERE id = ?",
            (contenido_nuevo, propuesta_id),
        )


def listar_pendientes_conversacion(conversacion_id: str) -> list[Propuesta]:
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT * FROM propuestas WHERE conversacion_id = ? AND estado = 'pendiente' ORDER BY creado ASC",
            (conversacion_id,),
        ).fetchall()
    return [_row_a_propuesta(r) for r in rows]


def listar_pendientes_proyecto(proyecto_slug: str) -> list[Propuesta]:
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT * FROM propuestas WHERE proyecto_slug = ? AND estado = 'pendiente' ORDER BY creado ASC",
            (proyecto_slug,),
        ).fetchall()
    return [_row_a_propuesta(r) for r in rows]


def nuevo_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Serialización para el frontend
# ---------------------------------------------------------------------------

def serializar(p: Propuesta) -> dict:
    base = {
        "id": p.id,
        "tipo": p.tipo,
        "motivo": p.motivo,
        "estado": p.estado,
        "creado": p.creado,
    }
    if p.tipo == "modificar_fichero":
        base.update(
            {
                "ruta": p.ruta,
                "contenido_nuevo": p.contenido_nuevo,
                "diff": generar_diff(
                    p.contenido_anterior or "", p.contenido_nuevo or "", p.ruta or ""
                ),
            }
        )
    elif p.tipo == "crear_fichero":
        base.update(
            {
                "ruta": p.ruta,
                "contenido_nuevo": p.contenido_nuevo,
                "diff": generar_diff("", p.contenido_nuevo or "", p.ruta or ""),
            }
        )
    elif p.tipo == "reordenar_capitulos":
        base.update(
            {
                "nuevo_orden": p.nuevo_orden,
                "orden_anterior": p.orden_anterior,
            }
        )
    elif p.tipo == "actualizar_grafo_relaciones":
        base.update({"cambios": p.cambios})
    return base


def generar_diff(antes: str, despues: str, etiqueta: str) -> str:
    lineas_antes = antes.splitlines(keepends=True)
    lineas_despues = despues.splitlines(keepends=True)
    if lineas_antes and not lineas_antes[-1].endswith("\n"):
        lineas_antes[-1] += "\n"
    if lineas_despues and not lineas_despues[-1].endswith("\n"):
        lineas_despues[-1] += "\n"
    diff = difflib.unified_diff(
        lineas_antes,
        lineas_despues,
        fromfile=f"a/{etiqueta}",
        tofile=f"b/{etiqueta}",
        n=3,
    )
    return "".join(diff)
