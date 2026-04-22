"""Wrapper sobre el binario git vía subprocess.

Un único usuario, un único thread de escritura por proyecto (lock).
No hay concurrencia real; el lock previene solapes con el push en background.
"""
from __future__ import annotations

import logging
import queue
import subprocess
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


log = logging.getLogger("novela_app.git")

# Locks por proyecto (clave: path absoluto como string).
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()

# Estado de push por proyecto para exponer en git_status.
_push_state: dict[str, dict] = {}
_push_state_lock = threading.Lock()

# Cola global de pushes en background.
_push_queue: queue.Queue = queue.Queue()
_push_thread: threading.Thread | None = None
_push_thread_lock = threading.Lock()


@contextmanager
def proyecto_lock(proyecto_ruta: Path, timeout: float = 10.0):
    key = str(proyecto_ruta.resolve())
    with _locks_guard:
        lock = _locks.setdefault(key, threading.Lock())
    adquirido = lock.acquire(timeout=timeout)
    if not adquirido:
        raise RuntimeError(f"Timeout adquiriendo lock del proyecto {proyecto_ruta}")
    try:
        yield
    finally:
        lock.release()


class GitError(RuntimeError):
    pass


def _run(
    args: list[str],
    cwd: Path,
    check: bool = True,
    capture: bool = True,
) -> subprocess.CompletedProcess:
    res = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=capture,
        text=True,
    )
    if check and res.returncode != 0:
        raise GitError(
            f"git {' '.join(args)} falló ({res.returncode}): {res.stderr.strip() or res.stdout.strip()}"
        )
    return res


def init_repo(
    proyecto_ruta: Path,
    autor_nombre: str,
    autor_email: str,
    remoto_url: str | None = None,
) -> None:
    """Inicializa git en el proyecto, configura autor, primer commit.

    Si `remoto_url` se pasa (y no está vacío), configura el remoto origin y
    prepara el tracking con main. No hace push inmediato (lo hará el siguiente
    commit si auto_push está activo en la config del proyecto).
    """
    with proyecto_lock(proyecto_ruta):
        _run(["init", "-b", "main"], proyecto_ruta)
        _run(["config", "user.name", autor_nombre], proyecto_ruta)
        _run(["config", "user.email", autor_email], proyecto_ruta)
        _run(["add", "."], proyecto_ruta)
        _run(["commit", "-m", "[SYS] Inicialización del proyecto"], proyecto_ruta)
        if remoto_url:
            _run(["remote", "add", "origin", remoto_url], proyecto_ruta, check=False)


def commit_cambios(
    proyecto_ruta: Path, mensaje: str, paths: list[str] | None = None
) -> str | None:
    """Añade y commitea los paths indicados (o todo si None). Devuelve el hash.

    Si la config del proyecto tiene `git.auto_push: true`, encola un push en
    background tras el commit. No bloquea.
    """
    with proyecto_lock(proyecto_ruta):
        if paths:
            _run(["add", "--", *paths], proyecto_ruta)
        else:
            _run(["add", "-A"], proyecto_ruta)

        status = _run(["status", "--porcelain"], proyecto_ruta)
        if not status.stdout.strip():
            return None

        _run(["commit", "-m", mensaje], proyecto_ruta)
        res = _run(["rev-parse", "HEAD"], proyecto_ruta)
        commit_hash = res.stdout.strip()

    if _debe_auto_push(proyecto_ruta):
        encolar_push(proyecto_ruta)

    return commit_hash


def _debe_auto_push(proyecto_ruta: Path) -> bool:
    import json

    cfg_path = proyecto_ruta / ".novela-config.json"
    if not cfg_path.exists():
        cfg_path = proyecto_ruta / ".libro-config.json"
        if not cfg_path.exists():
            return False
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    git_cfg = cfg.get("git") or {}
    if not git_cfg.get("auto_push"):
        return False
    return bool(git_cfg.get("remoto_url"))


def ultimo_commit_de_fichero(proyecto_ruta: Path, ruta_rel: str) -> str | None:
    res = _run(
        ["log", "-n", "1", "--pretty=format:%h", "--", ruta_rel],
        proyecto_ruta,
        check=False,
    )
    hash_ = res.stdout.strip()
    return hash_ or None


def git_status_info(proyecto_ruta: Path) -> dict:
    """Resumen para /api/proyecto/<slug>/git_status."""
    last_commit = ""
    last_date = ""
    try:
        last = _run(["log", "-n", "1", "--pretty=format:%h %cI"], proyecto_ruta, check=False)
        if last.stdout.strip():
            partes = last.stdout.strip().split(" ", 1)
            last_commit = partes[0]
            last_date = partes[1] if len(partes) > 1 else ""
    except GitError:
        pass

    remoto_url = None
    try:
        r = _run(["remote", "get-url", "origin"], proyecto_ruta, check=False)
        remoto_url = r.stdout.strip() or None
    except GitError:
        pass

    commits_pendientes = 0
    if remoto_url:
        r = _run(["rev-list", "--count", "origin/main..HEAD"], proyecto_ruta, check=False)
        try:
            commits_pendientes = int(r.stdout.strip() or "0")
        except ValueError:
            commits_pendientes = 0

    clave = str(proyecto_ruta.resolve())
    with _push_state_lock:
        push_info = _push_state.get(clave, {})

    if not remoto_url:
        estado = "local"
    elif push_info.get("ultimo_error"):
        estado = "error"
    elif commits_pendientes > 0:
        estado = "pendiente"
    else:
        estado = "sincronizado"

    return {
        "estado": estado,
        "commits_pendientes": commits_pendientes,
        "ultimo_push": push_info.get("ultimo_push"),
        "ultimo_commit": last_commit or None,
        "ultimo_commit_fecha": last_date or None,
        "remoto_url": remoto_url,
        "error_ultimo": push_info.get("ultimo_error"),
    }


def revert_head(proyecto_ruta: Path) -> str | None:
    """Revierte el último commit. Devuelve el hash del nuevo commit de revert."""
    with proyecto_lock(proyecto_ruta):
        # git revert HEAD --no-edit crea un commit nuevo con los cambios invertidos.
        res = _run(["log", "-n", "1", "--pretty=format:%s"], proyecto_ruta, check=False)
        asunto_anterior = res.stdout.strip()
        _run(["revert", "HEAD", "--no-edit"], proyecto_ruta)
        r2 = _run(["rev-parse", "HEAD"], proyecto_ruta)
        nuevo_hash = r2.stdout.strip()
        log.info("Revertido commit '%s' → nuevo hash %s", asunto_anterior, nuevo_hash)
        return nuevo_hash


# ---------------------------------------------------------------------------
# Push en background
# ---------------------------------------------------------------------------

def _push_worker() -> None:
    while True:
        ruta: Path = _push_queue.get()
        if ruta is None:
            return
        clave = str(ruta.resolve())
        try:
            with proyecto_lock(ruta, timeout=30.0):
                # Sólo pushea si hay remoto configurado.
                r = _run(["remote", "get-url", "origin"], ruta, check=False)
                if not r.stdout.strip():
                    _registrar_push(clave, error="sin remoto configurado")
                    continue
                _run(["push", "-u", "origin", "main"], ruta)
                _registrar_push(clave, error=None)
        except Exception as exc:  # noqa: BLE001
            log.exception("Error en push de %s", ruta)
            _registrar_push(clave, error=str(exc))
        finally:
            _push_queue.task_done()


def _registrar_push(clave: str, error: str | None) -> None:
    with _push_state_lock:
        _push_state[clave] = {
            "ultimo_push": datetime.now(timezone.utc).isoformat() if error is None else _push_state.get(clave, {}).get("ultimo_push"),
            "ultimo_error": error,
        }


def _asegurar_worker_push() -> None:
    global _push_thread
    with _push_thread_lock:
        if _push_thread is not None and _push_thread.is_alive():
            return
        _push_thread = threading.Thread(
            target=_push_worker, name="git-push-worker", daemon=True
        )
        _push_thread.start()


def encolar_push(proyecto_ruta: Path) -> None:
    """Encola un push asíncrono. No bloquea."""
    _asegurar_worker_push()
    _push_queue.put(proyecto_ruta)


def historial_de_fichero(proyecto_ruta: Path, ruta_rel: str) -> list[dict]:
    """git log por fichero con formato estable."""
    sep = "%x1f"
    fmt = sep.join(["%H", "%h", "%cI", "%an", "%s"])
    res = _run(
        ["log", f"--pretty=format:{fmt}", "--", ruta_rel],
        proyecto_ruta,
        check=False,
    )
    versiones: list[dict] = []
    for linea in res.stdout.splitlines():
        partes = linea.split("\x1f")
        if len(partes) != 5:
            continue
        hash_full, hash_short, fecha, autor, mensaje = partes
        autor_tag = _extraer_autor_tag(mensaje)
        motivo = _extraer_motivo(mensaje)
        versiones.append(
            {
                "commit": hash_short,
                "commit_full": hash_full,
                "fecha": fecha,
                "autor": autor_tag or autor,
                "motivo": motivo or mensaje,
            }
        )
    return versiones


def contenido_en_commit(proyecto_ruta: Path, ruta_rel: str, commit: str) -> str:
    res = _run(["show", f"{commit}:{ruta_rel}"], proyecto_ruta)
    return res.stdout


def _extraer_autor_tag(mensaje: str) -> str | None:
    if mensaje.startswith("[IA]"):
        return "IA"
    if mensaje.startswith("[YO]"):
        return "YO"
    if mensaje.startswith("[SYS]"):
        return "SYS"
    return None


def _extraer_motivo(mensaje: str) -> str | None:
    for tag in ("[IA]", "[YO]", "[SYS]"):
        if mensaje.startswith(tag):
            resto = mensaje[len(tag):].strip()
            if ":" in resto:
                return resto.split(":", 1)[1].strip()
            return resto
    return None
