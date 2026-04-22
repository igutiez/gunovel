"""Endpoints REST para la capa de ficheros."""
from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, abort, jsonify, request
from flask_login import current_user, login_required

from ..audit.db import registrar_evento
from ..versioning.git_ops import commit_cambios, ultimo_commit_de_fichero
from .parser import (
    RutaNoPermitidaError,
    SlugInvalidoError,
    escribir_fichero,
    parse_fichero,
    ruta_segura,
    validar_frontmatter,
)
from .project import (
    CARPETAS_TITULOS,
    ProyectoNoEncontrado,
    añadir_libro_a_saga,
    cargar_proyecto,
    construir_arbol,
    crear_proyecto_independiente,
    crear_saga,
    escribir_orden,
    leer_orden,
    listar_proyectos,
    numerar_capitulos,
)


bp = Blueprint("files", __name__, url_prefix="/api")


def _cargar_o_404(slug: str):
    try:
        return cargar_proyecto(slug)
    except ProyectoNoEncontrado:
        abort(404, description=f"Proyecto '{slug}' no encontrado.")


@bp.get("/proyectos")
@login_required
def api_proyectos():
    return jsonify(listar_proyectos())


@bp.post("/proyectos")
@login_required
def api_crear_proyecto():
    data = request.get_json(silent=True) or {}
    slug = (data.get("slug") or "").strip()
    nombre = (data.get("nombre") or slug).strip()
    if not slug:
        abort(400, description="Falta 'slug'.")
    if not nombre:
        nombre = slug
    from .parser import SlugInvalidoError

    try:
        ruta = crear_proyecto_independiente(slug=slug, nombre=nombre)
    except SlugInvalidoError as exc:
        abort(400, description=str(exc))
    except FileExistsError as exc:
        abort(409, description=str(exc))

    registrar_evento(
        tipo="sistema_init",
        proyecto_slug=slug,
        resultado=f"novela_creada:{ruta}",
    )
    return jsonify(
        {
            "ok": True,
            "slug": slug,
            "nombre": nombre,
            "ruta": f"independientes/{slug}",
        }
    ), 201


@bp.post("/sagas")
@login_required
def api_crear_saga():
    data = request.get_json(silent=True) or {}
    slug = (data.get("slug") or "").strip()
    nombre = (data.get("nombre") or slug).strip()
    if not slug:
        abort(400, description="Falta 'slug'.")
    from .parser import SlugInvalidoError

    try:
        ruta = crear_saga(slug=slug, nombre=nombre or slug)
    except SlugInvalidoError as exc:
        abort(400, description=str(exc))
    except FileExistsError as exc:
        abort(409, description=str(exc))

    registrar_evento(
        tipo="sistema_init",
        proyecto_slug=slug,
        resultado=f"saga_creada:{ruta}",
    )
    return jsonify({"ok": True, "slug": slug, "nombre": nombre}), 201


@bp.post("/saga/<saga_slug>/libros")
@login_required
def api_añadir_libro(saga_slug: str):
    data = request.get_json(silent=True) or {}
    libro_slug = (data.get("slug") or "").strip()
    libro_nombre = (data.get("nombre") or libro_slug).strip()
    orden = int(data.get("orden") or 0)
    if not libro_slug:
        abort(400, description="Falta 'slug' del libro.")
    from .parser import SlugInvalidoError

    try:
        ruta = añadir_libro_a_saga(saga_slug, libro_slug, libro_nombre, orden)
    except ProyectoNoEncontrado as exc:
        abort(404, description=str(exc))
    except SlugInvalidoError as exc:
        abort(400, description=str(exc))
    except FileExistsError as exc:
        abort(409, description=str(exc))

    slug_compuesto = f"{saga_slug}/{libro_slug}"
    registrar_evento(
        tipo="sistema_init",
        proyecto_slug=slug_compuesto,
        resultado=f"libro_creado:{ruta}",
    )
    return jsonify({"ok": True, "slug": slug_compuesto, "nombre": libro_nombre}), 201


@bp.get("/proyecto/<slug>/arbol")
@login_required
def api_arbol(slug: str):
    proyecto = _cargar_o_404(slug)
    return jsonify(construir_arbol(proyecto))


@bp.get("/proyecto/<slug>/fichero")
@login_required
def api_leer(slug: str):
    proyecto = _cargar_o_404(slug)
    ruta_rel = request.args.get("ruta", "")
    try:
        abs_path = ruta_segura(proyecto.ruta, ruta_rel)
    except RutaNoPermitidaError as exc:
        abort(400, description=str(exc))
    if not abs_path.exists() or not abs_path.is_file():
        abort(404, description="Fichero no encontrado.")
    parsed = parse_fichero(abs_path)
    stat = abs_path.stat()
    return jsonify(
        {
            "ruta": ruta_rel,
            "metadata": parsed["metadata"],
            "title": parsed["title"],
            "content": parsed["content"],
            "last_modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            "last_commit": ultimo_commit_de_fichero(proyecto.ruta, ruta_rel),
        }
    )


@bp.put("/proyecto/<slug>/fichero")
@login_required
def api_modificar(slug: str):
    proyecto = _cargar_o_404(slug)
    data = request.get_json(silent=True) or {}
    ruta_rel = data.get("ruta", "")
    contenido_bruto = data.get("content")
    commit_message = (data.get("commit_message") or "Edición manual").strip()
    if contenido_bruto is None:
        abort(400, description="Falta 'content'.")

    try:
        abs_path = ruta_segura(proyecto.ruta, ruta_rel)
    except RutaNoPermitidaError as exc:
        abort(400, description=str(exc))
    if not abs_path.exists():
        abort(404, description="Fichero no encontrado.")

    # Si el contenido viene con frontmatter embebido, `python-frontmatter`
    # lo detecta al parsear; para simplificar, escribimos tal cual el string.
    # El cliente del editor manda el contenido completo ya formateado.
    from .parser import escribir_raw

    escribir_raw(abs_path, _asegurar_newline_final(contenido_bruto))

    commit_hash = commit_cambios(
        proyecto_ruta=proyecto.ruta,
        mensaje=f"[YO] {ruta_rel}: {commit_message}",
        paths=[ruta_rel],
    )
    registrar_evento(
        tipo="usuario_edicion",
        proyecto_slug=proyecto.slug,
        fichero=ruta_rel,
        commit_git=commit_hash,
        mensaje_usuario=commit_message,
        resultado="ok",
    )
    return jsonify({"ok": True, "commit": commit_hash})


@bp.post("/proyecto/<slug>/fichero")
@login_required
def api_crear(slug: str):
    proyecto = _cargar_o_404(slug)
    data = request.get_json(silent=True) or {}
    ruta_rel = data.get("ruta", "")
    contenido = data.get("content", "")
    commit_message = (data.get("commit_message") or "Fichero creado").strip()

    try:
        abs_path = ruta_segura(proyecto.ruta, ruta_rel)
    except RutaNoPermitidaError as exc:
        abort(400, description=str(exc))
    if abs_path.exists():
        abort(409, description="El fichero ya existe.")
    if not abs_path.name.endswith(".md") and "." not in abs_path.name:
        abort(400, description="El fichero debe tener extensión .md.")

    from .parser import escribir_raw

    escribir_raw(abs_path, _asegurar_newline_final(contenido))

    commit_hash = commit_cambios(
        proyecto_ruta=proyecto.ruta,
        mensaje=f"[YO] {ruta_rel}: {commit_message}",
        paths=[ruta_rel],
    )
    registrar_evento(
        tipo="usuario_edicion",
        proyecto_slug=proyecto.slug,
        fichero=ruta_rel,
        commit_git=commit_hash,
        mensaje_usuario=commit_message,
        resultado="creado",
    )
    return jsonify({"ok": True, "commit": commit_hash}), 201


@bp.delete("/proyecto/<slug>/fichero")
@login_required
def api_borrar(slug: str):
    proyecto = _cargar_o_404(slug)
    ruta_rel = request.args.get("ruta") or (request.get_json(silent=True) or {}).get("ruta", "")
    try:
        abs_path = ruta_segura(proyecto.ruta, ruta_rel)
    except RutaNoPermitidaError as exc:
        abort(400, description=str(exc))
    if not abs_path.exists() or not abs_path.is_file():
        abort(404, description="Fichero no encontrado.")

    abs_path.unlink()

    # Si era un capítulo, quitarlo de orden.json.
    if ruta_rel.startswith("04_capitulos/"):
        slug_fichero = abs_path.stem
        orden = leer_orden(proyecto)
        orden["capitulos"] = [
            c for c in (orden.get("capitulos") or [])
            if (c.get("slug") if isinstance(c, dict) else c) != slug_fichero
        ]
        if orden.get("prologo", {}).get("slug") == slug_fichero:
            orden.pop("prologo", None)
        if orden.get("epilogo", {}).get("slug") == slug_fichero:
            orden.pop("epilogo", None)
        escribir_orden(proyecto, orden)

    commit_hash = commit_cambios(
        proyecto_ruta=proyecto.ruta,
        mensaje=f"[YO] {ruta_rel}: fichero eliminado",
        paths=None,
    )
    registrar_evento(
        tipo="usuario_edicion",
        proyecto_slug=proyecto.slug,
        fichero=ruta_rel,
        commit_git=commit_hash,
        resultado="borrado",
    )
    return jsonify({"ok": True, "commit": commit_hash})


@bp.post("/proyecto/<slug>/fichero/renombrar")
@login_required
def api_renombrar(slug: str):
    proyecto = _cargar_o_404(slug)
    data = request.get_json(silent=True) or {}
    ruta_rel = data.get("ruta", "")
    nuevo_slug = (data.get("nuevo_slug") or "").strip()
    if not nuevo_slug:
        abort(400, description="Falta 'nuevo_slug'.")
    from .parser import validar_slug

    try:
        validar_slug(nuevo_slug)
    except SlugInvalidoError as exc:
        abort(400, description=str(exc))

    try:
        abs_origen = ruta_segura(proyecto.ruta, ruta_rel)
    except RutaNoPermitidaError as exc:
        abort(400, description=str(exc))
    if not abs_origen.exists() or not abs_origen.is_file():
        abort(404, description="Fichero no encontrado.")

    from pathlib import Path as _P

    p = _P(ruta_rel)
    nueva_ruta_rel = f"{p.parent.as_posix()}/{nuevo_slug}.md"
    try:
        abs_destino = ruta_segura(proyecto.ruta, nueva_ruta_rel)
    except RutaNoPermitidaError as exc:
        abort(400, description=str(exc))
    if abs_destino.exists():
        abort(409, description=f"Ya existe: {nueva_ruta_rel}")

    # Git mv preserva historial; usamos subprocess directo para no duplicar lógica.
    from ..versioning.git_ops import _run as _gitrun
    from ..versioning.git_ops import proyecto_lock

    with proyecto_lock(proyecto.ruta):
        _gitrun(["mv", "--", ruta_rel, nueva_ruta_rel], proyecto.ruta)

    # Actualizar slug en frontmatter si coincidía con el antiguo.
    slug_viejo = abs_origen.stem
    try:
        parsed = parse_fichero(abs_destino)
        meta = parsed["metadata"] or {}
        if meta.get("slug") == slug_viejo:
            meta["slug"] = nuevo_slug
            escribir_fichero(abs_destino, meta, parsed["content"])
    except Exception:
        pass

    # Actualizar orden.json si era capítulo.
    if ruta_rel.startswith("04_capitulos/"):
        orden = leer_orden(proyecto)
        orden["capitulos"] = [
            {"slug": nuevo_slug} if (c.get("slug") if isinstance(c, dict) else c) == slug_viejo else c
            for c in (orden.get("capitulos") or [])
        ]
        for clave in ("prologo", "epilogo"):
            if orden.get(clave, {}).get("slug") == slug_viejo:
                orden[clave]["slug"] = nuevo_slug
        escribir_orden(proyecto, orden)

    commit_hash = commit_cambios(
        proyecto_ruta=proyecto.ruta,
        mensaje=f"[YO] {ruta_rel} → {nueva_ruta_rel}: renombrado",
        paths=None,
    )
    registrar_evento(
        tipo="usuario_edicion",
        proyecto_slug=proyecto.slug,
        fichero=nueva_ruta_rel,
        commit_git=commit_hash,
        resultado=f"renombrado_desde_{ruta_rel}",
    )
    return jsonify({"ok": True, "commit": commit_hash, "nueva_ruta": nueva_ruta_rel})


@bp.post("/proyecto/<slug>/reordenar")
@login_required
def api_reordenar(slug: str):
    proyecto = _cargar_o_404(slug)
    data = request.get_json(silent=True) or {}
    nuevo_orden = data.get("nuevo_orden")
    if not isinstance(nuevo_orden, list):
        abort(400, description="Se espera 'nuevo_orden' (lista de slugs).")

    orden = leer_orden(proyecto)
    orden["capitulos"] = [{"slug": s} for s in nuevo_orden]
    escribir_orden(proyecto, orden)

    commit_hash = commit_cambios(
        proyecto_ruta=proyecto.ruta,
        mensaje="[YO] 03_estructura/orden.json: reordenación de capítulos",
        paths=["03_estructura/orden.json"],
    )
    registrar_evento(
        tipo="usuario_reordenacion",
        proyecto_slug=proyecto.slug,
        fichero="03_estructura/orden.json",
        commit_git=commit_hash,
        resultado="ok",
    )
    return jsonify({"ok": True, "commit": commit_hash})


def _asegurar_newline_final(s: str) -> str:
    return s if s.endswith("\n") else s + "\n"
