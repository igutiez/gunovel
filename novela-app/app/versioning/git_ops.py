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


def _encontrar_repo_raiz(ruta: Path) -> Path | None:
    """Sube por los ancestros buscando un directorio con .git/.

    Devuelve el path del repo o None si no hay ninguno.
    """
    actual = ruta.resolve()
    while True:
        if (actual / ".git").exists():
            return actual
        if actual.parent == actual:
            return None
        actual = actual.parent


def _resolver_repo(proyecto_ruta: Path) -> tuple[Path, Path]:
    """Devuelve (repo_root, ruta_del_proyecto_relativa_al_repo).

    En modo monorepo (repo padre contiene al proyecto), el proyecto NO tiene
    su propio .git. En modo legacy (proyecto tiene su .git), repo_root ==
    proyecto_ruta y la ruta relativa es vacía.
    """
    repo = _encontrar_repo_raiz(proyecto_ruta)
    if repo is None:
        return proyecto_ruta, Path("")
    if repo == proyecto_ruta.resolve():
        return repo, Path("")
    try:
        rel = proyecto_ruta.resolve().relative_to(repo)
    except ValueError:
        return proyecto_ruta, Path("")
    return repo, rel


def _prefijar_paths(prefijo: Path, paths: list[str] | None) -> list[str] | None:
    if not paths:
        return paths
    if str(prefijo) in ("", "."):
        return paths
    return [(prefijo / p).as_posix() for p in paths]


# Locks por repo-raíz (clave: path absoluto como string).
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
    # El lock siempre se toma sobre el repo raíz; en modo monorepo,
    # dos proyectos distintos comparten el mismo repo y por tanto el lock.
    repo, _ = _resolver_repo(proyecto_ruta)
    key = str(repo.resolve())
    with _locks_guard:
        lock = _locks.setdefault(key, threading.Lock())
    adquirido = lock.acquire(timeout=timeout)
    if not adquirido:
        raise RuntimeError(f"Timeout adquiriendo lock del repo {repo}")
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
    """Inicializa git para un proyecto nuevo.

    Modo monorepo: si ya existe un repo en un ancestro (p.ej. NOVELAS_ROOT
    vive dentro de un repo), NO crea un .git/ propio. Sólo añade los
    ficheros del proyecto al repo padre con un commit [SYS] Inicialización.

    Modo legacy (proyecto aislado): crea su propio .git/ y opcionalmente el
    remoto.
    """
    repo, rel = _resolver_repo(proyecto_ruta)
    if repo != proyecto_ruta.resolve():
        # Monorepo: el repo padre ya existe.
        with proyecto_lock(proyecto_ruta):
            _run(["add", "--", rel.as_posix()], repo)
            status = _run(["status", "--porcelain"], repo)
            if status.stdout.strip():
                _run(
                    ["commit", "-m", f"[SYS] Inicialización del proyecto {rel.as_posix()}"],
                    repo,
                )
        if _debe_auto_push(proyecto_ruta):
            encolar_push(proyecto_ruta)
        return

    # Legacy: crear repo propio.
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
    """Añade y commitea en el repo que contiene al proyecto.

    En monorepo, los paths (relativos al proyecto) se prefijan con la ruta
    del proyecto respecto al repo para que `git add` funcione desde la raíz.
    El subject del commit también se prefija con el slug del proyecto para
    que un `git log` mezclado siga siendo legible.
    """
    repo, rel = _resolver_repo(proyecto_ruta)
    paths_rel = _prefijar_paths(rel, paths)
    if str(rel) not in ("", "."):
        mensaje = _prefijar_mensaje_con_proyecto(mensaje, rel)

    with proyecto_lock(proyecto_ruta):
        if paths_rel:
            _run(["add", "--", *paths_rel], repo)
        else:
            # -A sobre el proyecto entero en monorepo: sólo su subcarpeta.
            if str(rel) not in ("", "."):
                _run(["add", "-A", "--", rel.as_posix()], repo)
            else:
                _run(["add", "-A"], repo)

        # Chequear si hay cambios en el sub-scope relevante.
        estado_args = ["status", "--porcelain"]
        if str(rel) not in ("", "."):
            estado_args += ["--", rel.as_posix()]
        status = _run(estado_args, repo)
        if not status.stdout.strip():
            return None

        _run(["commit", "-m", mensaje], repo)
        res = _run(["rev-parse", "HEAD"], repo)
        commit_hash = res.stdout.strip()

    if _debe_auto_push(proyecto_ruta):
        encolar_push(proyecto_ruta)

    return commit_hash


def _slug_desde_rel(rel: Path) -> str:
    """Extrae el slug del proyecto a partir de su ruta relativa al repo."""
    partes = rel.parts
    if len(partes) >= 3 and partes[0] == "novelas" and partes[1] == "independientes":
        return partes[2]
    if len(partes) >= 4 and partes[0] == "novelas" and partes[1] == "sagas":
        return f"{partes[2]}/{partes[3]}"
    return partes[-1] if partes else ""


def _prefijar_mensaje_con_proyecto(mensaje: str, rel: Path) -> str:
    """Transforma '[IA] foo.md: motivo' en '[IA] <slug>/foo.md: motivo'."""
    import re

    slug = _slug_desde_rel(rel)
    if not slug:
        return mensaje
    m = re.match(r"^(\[[A-Z]+\])\s+(.+?)(:\s.*)$", mensaje, flags=re.DOTALL)
    if m:
        tag, ruta_interna, resto = m.groups()
        return f"{tag} {slug}/{ruta_interna}{resto}"
    return f"{mensaje} ({slug})"


def _debe_auto_push(proyecto_ruta: Path) -> bool:
    """Decide si tras un commit hay que encolar push.

    Modo monorepo: lee `.gunovel.json` del repo raíz.
    Modo legacy: lee `.novela-config.json` / `.libro-config.json` del proyecto.
    """
    import json

    repo, rel = _resolver_repo(proyecto_ruta)
    if str(rel) not in ("", "."):
        # Monorepo: config global en el repo padre.
        cfg_path = repo / ".gunovel.json"
        if not cfg_path.exists():
            # Por defecto auto-push si hay remoto configurado.
            r = _run(["remote", "get-url", "origin"], repo, check=False)
            return bool(r.stdout.strip())
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            return False
        if not cfg.get("auto_push", True):
            return False
        r = _run(["remote", "get-url", "origin"], repo, check=False)
        return bool(r.stdout.strip())

    # Legacy: config por proyecto.
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
    repo, rel = _resolver_repo(proyecto_ruta)
    path_repo = (rel / ruta_rel).as_posix() if str(rel) not in ("", ".") else ruta_rel
    res = _run(
        ["log", "-n", "1", "--pretty=format:%h", "--", path_repo],
        repo,
        check=False,
    )
    hash_ = res.stdout.strip()
    return hash_ or None


def git_status_info(proyecto_ruta: Path) -> dict:
    """Resumen para /api/proyecto/<slug>/git_status.

    En monorepo la info refleja el repo padre, pero los commits se filtran
    al subscope del proyecto cuando se solicita historial por ruta.
    """
    repo, rel = _resolver_repo(proyecto_ruta)
    last_commit = ""
    last_date = ""
    try:
        log_args = ["log", "-n", "1", "--pretty=format:%h %cI"]
        if str(rel) not in ("", "."):
            log_args += ["--", rel.as_posix()]
        last = _run(log_args, repo, check=False)
        if last.stdout.strip():
            partes = last.stdout.strip().split(" ", 1)
            last_commit = partes[0]
            last_date = partes[1] if len(partes) > 1 else ""
    except GitError:
        pass

    remoto_url = None
    try:
        r = _run(["remote", "get-url", "origin"], repo, check=False)
        remoto_url = r.stdout.strip() or None
    except GitError:
        pass

    commits_pendientes = 0
    if remoto_url:
        r = _run(["rev-list", "--count", "origin/main..HEAD"], repo, check=False)
        try:
            commits_pendientes = int(r.stdout.strip() or "0")
        except ValueError:
            commits_pendientes = 0

    clave = str(repo.resolve())
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
    """Revierte el último commit *del repo*. En monorepo afecta al monorepo."""
    repo, _ = _resolver_repo(proyecto_ruta)
    with proyecto_lock(proyecto_ruta):
        res = _run(["log", "-n", "1", "--pretty=format:%s"], repo, check=False)
        asunto_anterior = res.stdout.strip()
        _run(["revert", "HEAD", "--no-edit"], repo)
        r2 = _run(["rev-parse", "HEAD"], repo)
        nuevo_hash = r2.stdout.strip()
        log.info("Revertido commit '%s' → nuevo hash %s", asunto_anterior, nuevo_hash)
    if _debe_auto_push(proyecto_ruta):
        encolar_push(proyecto_ruta)
    return nuevo_hash


# ---------------------------------------------------------------------------
# Push en background
# ---------------------------------------------------------------------------

def _push_worker() -> None:
    while True:
        ruta: Path = _push_queue.get()
        if ruta is None:
            return
        repo, _ = _resolver_repo(ruta)
        clave = str(repo.resolve())
        try:
            with proyecto_lock(ruta, timeout=30.0):
                r = _run(["remote", "get-url", "origin"], repo, check=False)
                if not r.stdout.strip():
                    _registrar_push(clave, error="sin remoto configurado")
                    continue
                _run(["push", "-u", "origin", "main"], repo)
                _registrar_push(clave, error=None)
        except Exception as exc:  # noqa: BLE001
            log.exception("Error en push de %s", repo)
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
    repo, rel = _resolver_repo(proyecto_ruta)
    path_repo = (rel / ruta_rel).as_posix() if str(rel) not in ("", ".") else ruta_rel
    sep = "%x1f"
    fmt = sep.join(["%H", "%h", "%cI", "%an", "%s"])
    res = _run(
        ["log", "--follow", f"--pretty=format:{fmt}", "--", path_repo],
        repo,
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
    repo, rel = _resolver_repo(proyecto_ruta)
    path_repo = (rel / ruta_rel).as_posix() if str(rel) not in ("", ".") else ruta_rel
    res = _run(["show", f"{commit}:{path_repo}"], repo)
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
