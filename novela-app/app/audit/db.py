"""SQLite de audit trail y persistencia de mensajes de chat."""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from ..config import Config


_SCHEMA = """
CREATE TABLE IF NOT EXISTS eventos (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    proyecto_slug TEXT NOT NULL,
    tipo TEXT NOT NULL,
    fichero TEXT,
    commit_git TEXT,
    conversacion_id TEXT,
    mensaje_usuario TEXT,
    motivo_ia TEXT,
    tokens_input INTEGER,
    tokens_input_cached INTEGER,
    tokens_output INTEGER,
    coste_eur REAL,
    modelo TEXT,
    tool_calls_json TEXT,
    resultado TEXT
);
CREATE INDEX IF NOT EXISTS idx_eventos_proyecto ON eventos(proyecto_slug);
CREATE INDEX IF NOT EXISTS idx_eventos_fichero ON eventos(fichero);
CREATE INDEX IF NOT EXISTS idx_eventos_timestamp ON eventos(timestamp);
CREATE INDEX IF NOT EXISTS idx_eventos_conversacion ON eventos(conversacion_id);

CREATE TABLE IF NOT EXISTS conversaciones (
    id TEXT PRIMARY KEY,
    proyecto_slug TEXT NOT NULL,
    inicio TEXT NOT NULL,
    fin TEXT,
    titulo TEXT,
    mensajes_json TEXT,
    ficheros_tocados_json TEXT,
    coste_total_eur REAL
);
CREATE INDEX IF NOT EXISTS idx_conv_proyecto ON conversaciones(proyecto_slug);

CREATE TABLE IF NOT EXISTS mensajes_chat (
    id TEXT PRIMARY KEY,
    conversacion_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    rol TEXT NOT NULL,
    contenido TEXT NOT NULL,
    tool_calls_json TEXT,
    FOREIGN KEY (conversacion_id) REFERENCES conversaciones(id)
);
CREATE INDEX IF NOT EXISTS idx_mensajes_conv ON mensajes_chat(conversacion_id);

CREATE TABLE IF NOT EXISTS ejecuciones_autonomo (
    id TEXT PRIMARY KEY,
    proyecto_slug TEXT NOT NULL,
    estado TEXT NOT NULL,
    fase TEXT,
    modelo TEXT,
    presupuesto_eur REAL NOT NULL,
    coste_acumulado_eur REAL NOT NULL DEFAULT 0,
    inicio TEXT NOT NULL,
    fin TEXT,
    pausa_hasta TEXT,
    razon_pausa TEXT,
    conversacion_id TEXT,
    golden_reference_ruta TEXT,
    max_propuestas_cola INTEGER DEFAULT 20,
    pasos_ejecutados INTEGER DEFAULT 0,
    firma_ultimas_tools TEXT,
    ultima_actividad TEXT
);
CREATE INDEX IF NOT EXISTS idx_ejec_proyecto ON ejecuciones_autonomo(proyecto_slug, estado);

CREATE TABLE IF NOT EXISTS preguntas_autor (
    id TEXT PRIMARY KEY,
    ejecucion_id TEXT NOT NULL,
    proyecto_slug TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    pregunta TEXT NOT NULL,
    contexto TEXT,
    prioridad TEXT NOT NULL,
    respuesta TEXT,
    respondida_en TEXT,
    FOREIGN KEY (ejecucion_id) REFERENCES ejecuciones_autonomo(id)
);
CREATE INDEX IF NOT EXISTS idx_pregs_ejec ON preguntas_autor(ejecucion_id);
CREATE INDEX IF NOT EXISTS idx_pregs_proy ON preguntas_autor(proyecto_slug, respuesta);

CREATE TABLE IF NOT EXISTS propuestas (
    id TEXT PRIMARY KEY,
    tipo TEXT NOT NULL,
    proyecto_slug TEXT NOT NULL,
    conversacion_id TEXT,
    motivo TEXT NOT NULL,
    ruta TEXT,
    contenido_nuevo TEXT,
    contenido_anterior TEXT,
    nuevo_orden_json TEXT,
    orden_anterior_json TEXT,
    cambios_json TEXT,
    creado TEXT NOT NULL,
    estado TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_propuestas_conv ON propuestas(conversacion_id);
CREATE INDEX IF NOT EXISTS idx_propuestas_estado ON propuestas(proyecto_slug, estado);
"""


_lock = threading.Lock()


def _db_path() -> Path:
    Config.APP_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    return Config.AUDIT_DB


@contextmanager
def _conn():
    conn = sqlite3.connect(str(_db_path()))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def inicializar_db() -> None:
    with _lock, _conn() as c:
        c.executescript(_SCHEMA)


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat()


def registrar_evento(
    *,
    tipo: str,
    proyecto_slug: str,
    fichero: str | None = None,
    commit_git: str | None = None,
    conversacion_id: str | None = None,
    mensaje_usuario: str | None = None,
    motivo_ia: str | None = None,
    tokens: dict | None = None,
    modelo: str | None = None,
    tool_calls: list | None = None,
    resultado: str | None = None,
    coste_eur: float | None = None,
) -> str:
    tokens = tokens or {}
    event_id = str(uuid.uuid4())
    with _lock, _conn() as c:
        c.execute(
            """
            INSERT INTO eventos (
                id, timestamp, proyecto_slug, tipo, fichero, commit_git,
                conversacion_id, mensaje_usuario, motivo_ia,
                tokens_input, tokens_input_cached, tokens_output,
                coste_eur, modelo, tool_calls_json, resultado
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                _ahora(),
                proyecto_slug,
                tipo,
                fichero,
                commit_git,
                conversacion_id,
                mensaje_usuario,
                motivo_ia,
                tokens.get("input"),
                tokens.get("cached"),
                tokens.get("output"),
                coste_eur,
                modelo,
                json.dumps(tool_calls, ensure_ascii=False) if tool_calls else None,
                resultado,
            ),
        )
    return event_id


# ---------------------------------------------------------------------------
# Conversaciones / mensajes de chat
# ---------------------------------------------------------------------------

def crear_conversacion(proyecto_slug: str, titulo: str | None = None) -> str:
    conv_id = str(uuid.uuid4())
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO conversaciones (id, proyecto_slug, inicio, titulo, coste_total_eur) VALUES (?, ?, ?, ?, 0)",
            (conv_id, proyecto_slug, _ahora(), titulo),
        )
    return conv_id


def añadir_mensaje(
    conversacion_id: str,
    rol: str,
    contenido: str,
    tool_calls: list | None = None,
) -> str:
    mid = str(uuid.uuid4())
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO mensajes_chat (id, conversacion_id, timestamp, rol, contenido, tool_calls_json) VALUES (?, ?, ?, ?, ?, ?)",
            (
                mid,
                conversacion_id,
                _ahora(),
                rol,
                contenido,
                json.dumps(tool_calls, ensure_ascii=False) if tool_calls else None,
            ),
        )
    return mid


def mensajes_de_conversacion(conversacion_id: str) -> list[dict]:
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT id, timestamp, rol, contenido, tool_calls_json FROM mensajes_chat WHERE conversacion_id = ? ORDER BY timestamp ASC",
            (conversacion_id,),
        ).fetchall()
    resultado = []
    for r in rows:
        resultado.append(
            {
                "id": r["id"],
                "timestamp": r["timestamp"],
                "rol": r["rol"],
                "contenido": r["contenido"],
                "tool_calls": json.loads(r["tool_calls_json"]) if r["tool_calls_json"] else None,
            }
        )
    return resultado


def conversaciones_de_proyecto(proyecto_slug: str) -> list[dict]:
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT id, inicio, fin, titulo, coste_total_eur FROM conversaciones WHERE proyecto_slug = ? ORDER BY inicio DESC",
            (proyecto_slug,),
        ).fetchall()
    return [dict(r) for r in rows]


def acumular_coste_conversacion(conversacion_id: str, coste_eur: float) -> None:
    with _lock, _conn() as c:
        c.execute(
            "UPDATE conversaciones SET coste_total_eur = COALESCE(coste_total_eur,0) + ? WHERE id = ?",
            (coste_eur, conversacion_id),
        )


# ---------------------------------------------------------------------------
# Consultas
# ---------------------------------------------------------------------------

def eventos_proyecto(
    proyecto_slug: str,
    fichero: str | None = None,
    desde: str | None = None,
    hasta: str | None = None,
    tipo: str | None = None,
    conversacion: str | None = None,
    buscar: str | None = None,
    limite: int = 200,
) -> list[dict]:
    query = "SELECT * FROM eventos WHERE proyecto_slug = ?"
    args: list = [proyecto_slug]
    if fichero:
        query += " AND fichero = ?"
        args.append(fichero)
    if desde:
        query += " AND timestamp >= ?"
        args.append(desde)
    if hasta:
        query += " AND timestamp <= ?"
        args.append(hasta)
    if tipo:
        query += " AND tipo = ?"
        args.append(tipo)
    if conversacion:
        query += " AND conversacion_id = ?"
        args.append(conversacion)
    if buscar:
        query += " AND (mensaje_usuario LIKE ? OR motivo_ia LIKE ?)"
        like = f"%{buscar}%"
        args.extend([like, like])
    query += " ORDER BY timestamp DESC LIMIT ?"
    args.append(limite)

    with _lock, _conn() as c:
        rows = c.execute(query, args).fetchall()
    return [dict(r) for r in rows]


def resumen_proyecto(proyecto_slug: str) -> dict:
    with _lock, _conn() as c:
        total = c.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(coste_eur),0) AS coste, COALESCE(SUM(tokens_input),0) AS ti, COALESCE(SUM(tokens_input_cached),0) AS tc, COALESCE(SUM(tokens_output),0) AS to_ FROM eventos WHERE proyecto_slug = ?",
            (proyecto_slug,),
        ).fetchone()
        por_tipo = c.execute(
            "SELECT tipo, COUNT(*) AS n FROM eventos WHERE proyecto_slug = ? GROUP BY tipo",
            (proyecto_slug,),
        ).fetchall()
    return {
        "total_eventos": total["n"],
        "total_coste_eur": total["coste"],
        "tokens_totales": {
            "input": total["ti"],
            "input_cached": total["tc"],
            "output": total["to_"],
        },
        "eventos_por_tipo": {r["tipo"]: r["n"] for r in por_tipo},
    }
