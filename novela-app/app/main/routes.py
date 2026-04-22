"""Rutas de vista principal."""
from __future__ import annotations

from flask import Blueprint, Response, abort, render_template
from flask_login import current_user, login_required

from ..files.project import ProyectoNoEncontrado, cargar_proyecto
from .export import construir_epub


bp = Blueprint("main", __name__)


@bp.get("/app")
@login_required
def app_view():
    return render_template("app.html", username=current_user.username)


@bp.get("/api/proyecto/<slug>/export/epub")
@login_required
def api_export_epub(slug: str):
    try:
        proyecto = cargar_proyecto(slug)
    except ProyectoNoEncontrado:
        abort(404, description=f"Proyecto '{slug}' no encontrado.")
    data = construir_epub(proyecto)
    nombre_archivo = f"{proyecto.slug.replace('/', '_')}.epub"
    return Response(
        data,
        mimetype="application/epub+zip",
        headers={
            "Content-Disposition": f'attachment; filename="{nombre_archivo}"',
            "Content-Length": str(len(data)),
        },
    )
