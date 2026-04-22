"""Endpoints REST para versionado."""
from __future__ import annotations

from flask import Blueprint, abort, jsonify, request
from flask_login import login_required

from ..audit.db import registrar_evento
from ..files.parser import RutaNoPermitidaError, escribir_raw, ruta_segura
from ..files.project import ProyectoNoEncontrado, cargar_proyecto
from .git_ops import (
    _run,
    commit_cambios,
    contenido_en_commit,
    encolar_push,
    git_status_info,
    historial_de_fichero,
    revert_head,
)


bp = Blueprint("versioning", __name__, url_prefix="/api")


def _cargar_o_404(slug: str):
    try:
        return cargar_proyecto(slug)
    except ProyectoNoEncontrado:
        abort(404, description=f"Proyecto '{slug}' no encontrado.")


@bp.get("/proyecto/<slug>/git_status")
@login_required
def api_git_status(slug: str):
    proyecto = _cargar_o_404(slug)
    return jsonify(git_status_info(proyecto.ruta))


@bp.get("/proyecto/<slug>/fichero/historial")
@login_required
def api_historial(slug: str):
    proyecto = _cargar_o_404(slug)
    ruta_rel = request.args.get("ruta", "")
    try:
        ruta_segura(proyecto.ruta, ruta_rel)
    except RutaNoPermitidaError as exc:
        abort(400, description=str(exc))
    return jsonify(
        {
            "ruta": ruta_rel,
            "versiones": historial_de_fichero(proyecto.ruta, ruta_rel),
        }
    )


@bp.get("/proyecto/<slug>/fichero/version")
@login_required
def api_version(slug: str):
    proyecto = _cargar_o_404(slug)
    ruta_rel = request.args.get("ruta", "")
    commit = request.args.get("commit", "")
    if not commit:
        abort(400, description="Falta 'commit'.")
    try:
        ruta_segura(proyecto.ruta, ruta_rel)
    except RutaNoPermitidaError as exc:
        abort(400, description=str(exc))
    try:
        contenido = contenido_en_commit(proyecto.ruta, ruta_rel, commit)
    except Exception as exc:  # GitError u otros
        abort(404, description=str(exc))
    return jsonify({"ruta": ruta_rel, "commit": commit, "content": contenido})


@bp.post("/proyecto/<slug>/fichero/restaurar")
@login_required
def api_restaurar(slug: str):
    proyecto = _cargar_o_404(slug)
    data = request.get_json(silent=True) or {}
    ruta_rel = data.get("ruta", "")
    commit = data.get("commit", "")
    if not commit:
        abort(400, description="Falta 'commit'.")
    try:
        abs_path = ruta_segura(proyecto.ruta, ruta_rel)
    except RutaNoPermitidaError as exc:
        abort(400, description=str(exc))

    contenido = contenido_en_commit(proyecto.ruta, ruta_rel, commit)
    escribir_raw(abs_path, contenido)

    commit_hash = commit_cambios(
        proyecto_ruta=proyecto.ruta,
        mensaje=f"[SYS] Restaurado {ruta_rel} a versión {commit}",
        paths=[ruta_rel],
    )
    registrar_evento(
        tipo="sistema_restauracion",
        proyecto_slug=proyecto.slug,
        fichero=ruta_rel,
        commit_git=commit_hash,
        resultado=f"restaurado_desde_{commit}",
    )
    return jsonify({"ok": True, "commit": commit_hash})


@bp.post("/proyecto/<slug>/deshacer")
@login_required
def api_deshacer(slug: str):
    proyecto = _cargar_o_404(slug)
    try:
        nuevo = revert_head(proyecto.ruta)
    except Exception as exc:  # noqa: BLE001
        abort(500, description=str(exc))
    registrar_evento(
        tipo="sistema_restauracion",
        proyecto_slug=proyecto.slug,
        commit_git=nuevo,
        resultado="revert_head",
    )
    return jsonify({"ok": True, "commit": nuevo})


@bp.post("/proyecto/<slug>/git/push")
@login_required
def api_push_manual(slug: str):
    proyecto = _cargar_o_404(slug)
    encolar_push(proyecto.ruta)
    return jsonify({"ok": True, "encolado": True})


@bp.post("/proyecto/<slug>/git/remoto")
@login_required
def api_configurar_remoto(slug: str):
    """Configura el remoto origin y actualiza .novela-config.json."""
    import json as _json

    proyecto = _cargar_o_404(slug)
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    auto_push = bool(data.get("auto_push", True))
    if not url:
        abort(400, description="Falta 'url'.")

    cfg_path = proyecto.ruta / ".novela-config.json"
    cfg = _json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
    cfg.setdefault("git", {})
    cfg["git"]["remoto_url"] = url
    cfg["git"]["auto_push"] = auto_push
    from ..files.parser import escribir_raw

    escribir_raw(cfg_path, _json.dumps(cfg, ensure_ascii=False, indent=2) + "\n")

    # Configurar en git el remoto (add o set-url si ya existía).
    existente = _run(["remote", "get-url", "origin"], proyecto.ruta, check=False).stdout.strip()
    if existente:
        _run(["remote", "set-url", "origin", url], proyecto.ruta)
    else:
        _run(["remote", "add", "origin", url], proyecto.ruta)

    commit_cambios(
        proyecto_ruta=proyecto.ruta,
        mensaje=f"[SYS] Configurado remoto origin: {url}",
        paths=[".novela-config.json"],
    )
    return jsonify({"ok": True, "remoto_url": url, "auto_push": auto_push})
