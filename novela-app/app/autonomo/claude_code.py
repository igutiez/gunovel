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

import json
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
        # Streaming de eventos: una línea JSON por evento (mensajes, tool_use,
        # tool_result). Sin esto, claude --print no emite stdout hasta
        # terminar y el usuario no ve progreso durante los 2-5 minutos que
        # puede tardar un capítulo.
        "--output-format",
        "stream-json",
        "--verbose",
        # bypassPermissions evita diálogos interactivos. La seguridad la
        # garantizan los hooks de `.claude/settings.json` (bloquean .env,
        # capítulos cerrados, y filtran comandos Bash peligrosos via `deny`).
        "--permission-mode",
        "bypassPermissions",
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

    # Leer stdout línea a línea (cada línea es un JSON de evento).
    try:
        assert proc.stdout is not None
        for linea in proc.stdout:
            linea = linea.rstrip("\n")
            if not linea:
                continue
            for evento_texto in _formatear_evento_stream_json(linea):
                sesion.log_lines.append(evento_texto)
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


def _formatear_evento_stream_json(linea: str) -> list[str]:
    """Convierte una línea JSON de stream-json en líneas humanas.

    El formato emite objetos como:
      {"type":"system","subtype":"init",...}
      {"type":"assistant","message":{"content":[{"type":"text","text":...},
          {"type":"tool_use","name":...,"input":...}]}}
      {"type":"user","message":{"content":[{"type":"tool_result","content":...}]}}
      {"type":"result","subtype":"success","total_cost_usd":...,"duration_ms":...}

    Si la línea no es JSON válido, se devuelve tal cual.
    """
    try:
        obj = json.loads(linea)
    except json.JSONDecodeError:
        return [linea]

    tipo = obj.get("type")
    out: list[str] = []
    if tipo == "system":
        sub = obj.get("subtype") or ""
        model = obj.get("model") or ""
        session_id = (obj.get("session_id") or "")[:8]
        out.append(f"[init] {sub} · model={model} · session={session_id}")
    elif tipo == "assistant":
        msg = obj.get("message") or {}
        for b in msg.get("content") or []:
            btype = b.get("type")
            if btype == "text":
                texto = (b.get("text") or "").strip()
                if texto:
                    for parr in _chunks(texto, 400):
                        out.append(f"[asistente] {parr}")
            elif btype == "tool_use":
                nombre = b.get("name") or "?"
                inp = b.get("input") or {}
                resumen = _resumen_input(nombre, inp)
                out.append(f"[tool_use] {nombre}({resumen})")
            elif btype == "thinking":
                pensamiento = (b.get("thinking") or "").strip()
                if pensamiento:
                    out.append(f"[thinking] {pensamiento[:200]}")
    elif tipo == "user":
        msg = obj.get("message") or {}
        for b in msg.get("content") or []:
            if b.get("type") == "tool_result":
                is_err = b.get("is_error")
                contenido = b.get("content")
                if isinstance(contenido, list):
                    texto = " ".join(
                        (c.get("text", "") if isinstance(c, dict) else str(c))
                        for c in contenido
                    )
                else:
                    texto = str(contenido or "")
                marca = "error" if is_err else "ok"
                out.append(f"[tool_result:{marca}] {texto[:300].replace(chr(10), ' ')}")
    elif tipo == "result":
        coste = obj.get("total_cost_usd")
        dur = obj.get("duration_ms")
        turns = obj.get("num_turns")
        sub = obj.get("subtype") or ""
        partes = [f"result:{sub}"]
        if turns is not None:
            partes.append(f"turns={turns}")
        if dur is not None:
            partes.append(f"{dur/1000:.1f}s")
        if coste is not None:
            partes.append(f"{coste:.4f} USD")
        out.append("[" + " · ".join(partes) + "]")
        texto_res = obj.get("result")
        if texto_res:
            for parr in _chunks(str(texto_res).strip(), 400):
                out.append(f"[resumen final] {parr}")
    else:
        # Tipo desconocido: volcar resumido.
        out.append(f"[{tipo or 'unknown'}] {linea[:200]}")
    return out


def _chunks(s: str, n: int) -> list[str]:
    if not s:
        return []
    return [s[i : i + n] for i in range(0, len(s), n)]


def _resumen_input(nombre: str, inp: dict) -> str:
    """Muestra los args más útiles sin volcar un capítulo entero."""
    if not inp:
        return ""
    if nombre in ("Read", "Edit", "Write", "MultiEdit", "NotebookEdit"):
        ruta = inp.get("file_path") or inp.get("path") or ""
        return ruta
    if nombre == "Bash":
        cmd = (inp.get("command") or "").replace("\n", " ")
        return cmd[:120]
    if nombre in ("Grep", "Glob"):
        return (inp.get("pattern") or inp.get("path") or "")[:120]
    if nombre.startswith("mcp__"):
        return ", ".join(f"{k}={_trunc(v)}" for k, v in inp.items() if k != "content")
    # Fallback: primeros 3 pares k=v
    partes = []
    for k, v in list(inp.items())[:3]:
        partes.append(f"{k}={_trunc(v)}")
    return ", ".join(partes)


def _trunc(v, n: int = 60) -> str:
    s = str(v)
    if len(s) > n:
        return s[:n - 3] + "..."
    return s


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
