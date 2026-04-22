"""Endpoints de consulta del audit."""
from __future__ import annotations

from flask import Blueprint, jsonify, request
from flask_login import login_required

from .db import eventos_proyecto, resumen_proyecto


bp = Blueprint("audit", __name__, url_prefix="/api")


@bp.get("/proyecto/<slug>/audit")
@login_required
def api_eventos(slug: str):
    args = request.args
    eventos = eventos_proyecto(
        proyecto_slug=slug,
        fichero=args.get("fichero"),
        desde=args.get("desde"),
        hasta=args.get("hasta"),
        tipo=args.get("tipo"),
        conversacion=args.get("conversacion"),
        buscar=args.get("buscar"),
        limite=int(args.get("limite", "200")),
    )
    return jsonify({"eventos": eventos})


@bp.get("/proyecto/<slug>/audit/resumen")
@login_required
def api_resumen(slug: str):
    return jsonify(resumen_proyecto(slug))
