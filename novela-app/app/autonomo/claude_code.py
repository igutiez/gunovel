"""Integración con el CLI `claude` (Claude Code) como backend agentivo.

La app lanza `claude --print --permission-mode acceptEdits` en subproceso
sobre el directorio del proyecto, pasándole una tarea. Claude Code planifica,
usa sus tools y el MCP server `gunovel`, y escribe directamente a disco.

Los commits los hace el CLI (o los recoge el auto-commit/watchdog después).
Captura el stdout y devuelve al frontend.

Para seguimiento en vivo, exponemos:
- iniciar_sesion(proyecto, prompt, modelo) -> lanza subprocess en background
  y devuelve un id.
- estado_sesion(id) -> running / finished, líneas de log capturadas.
- detener_sesion(id).

El proceso corre en un thread separado para no bloquear la request.
"""
from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from ..config import Config


log = logging.getLogger("novela_app.claude_code")


@dataclass
class SesionCC:
    id: str
    proyecto_slug: str
    cwd: str
    prompt: str
    modelo: str | None
    estado: str = "arrancando"  # arrancando | ejecutando | terminado | error | detenido
    pid: int | None = None
    inicio: float = field(default_factory=time.time)
    fin: float | None = None
    log_lines: list[str] = field(default_factory=list)
    exit_code: int | None = None
    error: str | None = None
    process: subprocess.Popen | None = field(default=None, repr=False)


_sesiones: dict[str, SesionCC] = {}
_lock = threading.Lock()


MODELOS_CC = {
    "default": None,
    "claude-sonnet-4-6": "sonnet",
    "claude-opus-4-7": "opus",
    "claude-haiku-4-5": "haiku",
}


def _mapear_modelo(modelo: str | None) -> str | None:
    if not modelo:
        return None
    return MODELOS_CC.get(modelo, modelo)


def iniciar_sesion(
    *,
    proyecto_slug: str,
    prompt: str,
    cwd: Path,
    modelo: str | None = None,
    permitir_cerrados: bool = False,
) -> SesionCC:
    sid = str(uuid.uuid4())
    sesion = SesionCC(
        id=sid,
        proyecto_slug=proyecto_slug,
        cwd=str(cwd),
        prompt=prompt,
        modelo=_mapear_modelo(modelo),
    )
    with _lock:
        _sesiones[sid] = sesion

    t = threading.Thread(
        target=_run_session,
        args=(sesion, permitir_cerrados),
        name=f"cc-{sid[:8]}",
        daemon=True,
    )
    t.start()
    return sesion


def _run_session(sesion: SesionCC, permitir_cerrados: bool) -> None:
    args = [
        "claude",
        "--print",
        "--permission-mode",
        "acceptEdits",
    ]
    if sesion.modelo:
        args.extend(["--model", sesion.modelo])

    # Variables de entorno: pasar la API key y marcar si se permite tocar caps cerrados.
    env = os.environ.copy()
    if Config.ANTHROPIC_API_KEY:
        env["ANTHROPIC_API_KEY"] = Config.ANTHROPIC_API_KEY
    if permitir_cerrados:
        env["GUNOVEL_ALLOW_CLOSED"] = "1"

    try:
        proc = subprocess.Popen(
            args,
            cwd=sesion.cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError:
        sesion.estado = "error"
        sesion.error = "El binario `claude` no está disponible en PATH del servidor."
        sesion.fin = time.time()
        return
    except Exception as exc:  # noqa: BLE001
        sesion.estado = "error"
        sesion.error = f"No se pudo lanzar claude: {exc}"
        sesion.fin = time.time()
        return

    sesion.pid = proc.pid
    sesion.process = proc
    sesion.estado = "ejecutando"

    # Enviar el prompt por stdin y cerrarlo.
    try:
        proc.stdin.write(sesion.prompt)
        proc.stdin.close()
    except Exception as exc:  # noqa: BLE001
        sesion.log_lines.append(f"[app] error enviando prompt: {exc}")

    # Leer stdout línea a línea.
    try:
        assert proc.stdout is not None
        for linea in proc.stdout:
            sesion.log_lines.append(linea.rstrip("\n"))
            # Retener máximo 10000 líneas para no reventar memoria.
            if len(sesion.log_lines) > 10000:
                sesion.log_lines = sesion.log_lines[-5000:]
    except Exception as exc:  # noqa: BLE001
        sesion.log_lines.append(f"[app] error leyendo stdout: {exc}")

    rc = proc.wait()
    sesion.exit_code = rc
    sesion.fin = time.time()
    if sesion.estado == "detenido":
        pass  # conservar
    elif rc == 0:
        sesion.estado = "terminado"
    else:
        sesion.estado = "error"
        sesion.error = f"claude terminó con exit code {rc}"


def obtener_sesion(sid: str) -> SesionCC | None:
    with _lock:
        return _sesiones.get(sid)


def detener_sesion(sid: str) -> bool:
    sesion = obtener_sesion(sid)
    if sesion is None or sesion.process is None:
        return False
    try:
        sesion.estado = "detenido"
        sesion.process.terminate()
        try:
            sesion.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            sesion.process.kill()
    except Exception:
        return False
    return True


def serializar(sesion: SesionCC, limite_lineas: int = 500) -> dict:
    return {
        "id": sesion.id,
        "proyecto_slug": sesion.proyecto_slug,
        "cwd": sesion.cwd,
        "modelo": sesion.modelo,
        "estado": sesion.estado,
        "pid": sesion.pid,
        "inicio": sesion.inicio,
        "fin": sesion.fin,
        "exit_code": sesion.exit_code,
        "error": sesion.error,
        "log_lines": sesion.log_lines[-limite_lineas:],
        "total_lineas": len(sesion.log_lines),
    }


def ultima_sesion_proyecto(proyecto_slug: str) -> SesionCC | None:
    with _lock:
        sesiones = [s for s in _sesiones.values() if s.proyecto_slug == proyecto_slug]
    if not sesiones:
        return None
    return max(sesiones, key=lambda s: s.inicio)
