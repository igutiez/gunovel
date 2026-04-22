"""Endpoints REST del modo autónomo."""
from __future__ import annotations

import logging

from flask import Blueprint, abort, jsonify, request
from flask_login import login_required

from ..ai import propuestas as prop_mod
from ..audit.db import registrar_evento
from ..config import Config
from ..files.project import ProyectoNoEncontrado, cargar_proyecto
from . import claude_code as cc
from . import db as autodb
from .orquestador import ejecutar_paso


bp = Blueprint("autonomo", __name__, url_prefix="/api")

log = logging.getLogger("novela_app.autonomo.routes")


def _cargar_o_404(slug: str):
    try:
        return cargar_proyecto(slug)
    except ProyectoNoEncontrado:
        abort(404, description=f"Proyecto '{slug}' no encontrado.")


@bp.post("/proyecto/<slug>/autonomo/iniciar")
@login_required
def api_iniciar(slug: str):
    proyecto = _cargar_o_404(slug)
    data = request.get_json(silent=True) or {}
    fase = (data.get("fase") or "todo").strip()
    modelo = data.get("modelo") or proyecto.config.get("modelo_por_defecto") or Config.MODELO_POR_DEFECTO
    presupuesto = float(data.get("presupuesto_eur") or 5.0)
    max_cola = int(data.get("max_propuestas_cola") or 20)
    golden = data.get("golden_reference_ruta") or None

    if presupuesto <= 0 or presupuesto > 200:
        abort(400, description="presupuesto_eur debe estar entre 0 y 200.")

    existente = autodb.ejecucion_activa_de_proyecto(slug)
    if existente:
        abort(409, description=f"Ya hay una ejecución activa (id {existente['id']}, estado {existente['estado']}). Detén o reanuda esa antes.")

    eid = autodb.crear_ejecucion(
        proyecto_slug=slug,
        fase=fase,
        modelo=modelo,
        presupuesto_eur=presupuesto,
        golden_reference_ruta=golden,
        max_propuestas_cola=max_cola,
    )
    registrar_evento(
        tipo="sistema_init",
        proyecto_slug=slug,
        resultado=f"autonomo_iniciado:{eid}:fase={fase}:budget={presupuesto}",
    )
    return jsonify({"ok": True, "ejecucion_id": eid, "estado": "ejecutando"}), 201


@bp.get("/proyecto/<slug>/autonomo/estado")
@login_required
def api_estado(slug: str):
    _cargar_o_404(slug)
    ejec = autodb.ejecucion_activa_de_proyecto(slug)
    if not ejec:
        return jsonify({"activa": False})
    pendientes_preguntas = autodb.preguntas_de_ejecucion(ejec["id"], solo_nuevas=True)
    cola_propuestas = len(prop_mod.listar_pendientes_proyecto(slug))
    return jsonify(
        {
            "activa": True,
            "ejecucion": ejec,
            "preguntas_pendientes": pendientes_preguntas,
            "cola_propuestas": cola_propuestas,
        }
    )


@bp.post("/proyecto/<slug>/autonomo/paso")
@login_required
def api_paso(slug: str):
    proyecto = _cargar_o_404(slug)
    ejec = autodb.ejecucion_activa_de_proyecto(slug)
    if not ejec:
        abort(404, description="No hay ejecución autónoma activa.")
    if ejec["estado"] != "ejecutando":
        return jsonify(
            {
                "ok": False,
                "motivo": f"Ejecución en estado '{ejec['estado']}'. Reanuda antes de pedir pasos.",
                "ejecucion": ejec,
            }
        ), 409

    resultado = ejecutar_paso(proyecto, ejec)
    return jsonify(
        {
            "ok": True,
            "ejecucion": resultado.ejecucion,
            "mensaje_asistente": resultado.mensaje_asistente,
            "propuestas_nuevas": resultado.propuestas_nuevas,
            "preguntas_nuevas": resultado.preguntas_nuevas,
            "coste_paso_eur": resultado.coste_paso_eur,
            "pausado": resultado.pausar,
            "razon_pausa": resultado.razon_pausa,
        }
    )


@bp.post("/proyecto/<slug>/autonomo/pausar")
@login_required
def api_pausar(slug: str):
    _cargar_o_404(slug)
    ejec = autodb.ejecucion_activa_de_proyecto(slug)
    if not ejec:
        abort(404, description="No hay ejecución activa.")
    autodb.actualizar_estado(ejec["id"], estado="pausado", razon_pausa="Pausado manualmente por el autor.")
    return jsonify({"ok": True})


@bp.post("/proyecto/<slug>/autonomo/reanudar")
@login_required
def api_reanudar(slug: str):
    _cargar_o_404(slug)
    ejec = autodb.ejecucion_activa_de_proyecto(slug)
    if not ejec:
        abort(404, description="No hay ejecución activa.")
    if ejec["estado"] == "esperando_autor":
        # Solo reanudar si todas las preguntas están respondidas.
        pend = autodb.preguntas_de_ejecucion(ejec["id"], solo_nuevas=True)
        if pend:
            abort(409, description=f"No se puede reanudar: {len(pend)} pregunta(s) sin responder.")
    autodb.actualizar_estado(ejec["id"], estado="ejecutando", razon_pausa=None)
    return jsonify({"ok": True})


@bp.post("/proyecto/<slug>/autonomo/detener")
@login_required
def api_detener(slug: str):
    _cargar_o_404(slug)
    ejec = autodb.ejecucion_activa_de_proyecto(slug)
    if not ejec:
        abort(404, description="No hay ejecución activa.")
    autodb.actualizar_estado(ejec["id"], estado="detenido", razon_pausa="Detenido manualmente.", marcar_fin=True)
    return jsonify({"ok": True})


# --- Preguntas al autor -----------------------------------------------------


# --- Claude Code como backend agentivo ------------------------------------

_PROMPT_CC_BASE = """Trabaja en la novela **{proyecto_slug}** del monorepo `gunovel`.

Reglas en:
- /CLAUDE.md del repo (léelo si no lo tienes en contexto).
- CLAUDE.md del proyecto en {ruta_proyecto}/CLAUDE.md (léelo).
- 05_control/plan_autonomo.md del proyecto si existe.

Tools MCP disponibles: mcp__gunovel__listar_proyectos, resumen_canon_actual,
obtener_info_capitulo, ver_capitulos_adyacentes, verificar_coherencia,
auditar_capitulo. Tu cwd está en la raíz del repo; las rutas de ficheros
del proyecto viven en `novelas/independientes/{proyecto_slug}/` (o la ruta
equivalente para libros de saga).

Tarea del autor para esta sesión:

{tarea}

Directrices:
- Empieza con resumen_canon_actual para ubicarte.
- Planea en tu TodoWrite antes de tocar ficheros.
- Commit por cada propuesta coherente con mensaje `[IA] {{slug_proyecto}}/{{ruta}}: {{motivo}}`.
- Si necesitas una decisión del autor que no está clara, añade la pregunta a `05_control/preguntas_autor.md` y termina la sesión.
- NO toques capítulos con estado `revisado` o `cerrado`: el hook PreToolUse te los bloqueará.
- Al terminar, deja un resumen claro de qué has hecho.
"""


@bp.post("/proyecto/<slug>/autonomo/cc/lanzar")
@login_required
def api_cc_lanzar(slug: str):
    proyecto = _cargar_o_404(slug)
    data = request.get_json(silent=True) or {}
    tarea = (data.get("tarea") or "").strip()
    modelo = data.get("modelo") or proyecto.config.get("modelo_por_defecto") or Config.MODELO_POR_DEFECTO
    permitir_cerrados = bool(data.get("permitir_cerrados", False))
    if not tarea:
        abort(400, description="Falta 'tarea'.")

    # Raíz del repo monorepo: padres hacia arriba hasta encontrar .git.
    cwd = proyecto.ruta
    while cwd != cwd.parent:
        if (cwd / ".git").exists():
            break
        cwd = cwd.parent

    prompt = _PROMPT_CC_BASE.format(
        proyecto_slug=slug,
        ruta_proyecto=str(proyecto.ruta.relative_to(cwd)),
        tarea=tarea,
    )

    sesion = cc.iniciar_sesion(
        proyecto_slug=slug,
        prompt=prompt,
        cwd=cwd,
        modelo=modelo,
        permitir_cerrados=permitir_cerrados,
    )
    registrar_evento(
        tipo="sistema_init",
        proyecto_slug=slug,
        resultado=f"cc_sesion_iniciada:{sesion.id}:modelo={modelo}",
    )
    return jsonify({"ok": True, "sesion_id": sesion.id, "estado": sesion.estado}), 201


@bp.get("/proyecto/<slug>/autonomo/cc/estado/<sesion_id>")
@login_required
def api_cc_estado(slug: str, sesion_id: str):
    _cargar_o_404(slug)
    sesion = cc.obtener_sesion(sesion_id)
    if sesion is None or sesion.proyecto_slug != slug:
        abort(404, description="Sesión no encontrada.")
    return jsonify(cc.serializar(sesion))


@bp.get("/proyecto/<slug>/autonomo/cc/ultima")
@login_required
def api_cc_ultima(slug: str):
    _cargar_o_404(slug)
    sesion = cc.ultima_sesion_proyecto(slug)
    if sesion is None:
        return jsonify({"activa": False})
    return jsonify({"activa": True, "sesion": cc.serializar(sesion)})


@bp.post("/proyecto/<slug>/autonomo/cc/detener/<sesion_id>")
@login_required
def api_cc_detener(slug: str, sesion_id: str):
    _cargar_o_404(slug)
    sesion = cc.obtener_sesion(sesion_id)
    if sesion is None or sesion.proyecto_slug != slug:
        abort(404, description="Sesión no encontrada.")
    ok = cc.detener_sesion(sesion_id)
    return jsonify({"ok": ok})


@bp.get("/proyecto/<slug>/autonomo/preguntas")
@login_required
def api_preguntas(slug: str):
    _cargar_o_404(slug)
    return jsonify({"preguntas": autodb.preguntas_pendientes(slug)})


@bp.post("/proyecto/<slug>/autonomo/preguntas/<pregunta_id>/responder")
@login_required
def api_responder(slug: str, pregunta_id: str):
    _cargar_o_404(slug)
    pregunta = autodb.obtener_pregunta(pregunta_id)
    if not pregunta or pregunta["proyecto_slug"] != slug:
        abort(404, description="Pregunta no encontrada.")
    data = request.get_json(silent=True) or {}
    respuesta = (data.get("respuesta") or "").strip()
    if not respuesta:
        abort(400, description="Falta 'respuesta'.")
    autodb.responder_pregunta(pregunta_id, respuesta)

    # Si era la última pendiente y el loop estaba esperando, reanudar.
    ejec = autodb.ejecucion_activa_de_proyecto(slug)
    if ejec and ejec["estado"] == "esperando_autor":
        restantes = autodb.preguntas_de_ejecucion(ejec["id"], solo_nuevas=True)
        if not restantes:
            autodb.actualizar_estado(ejec["id"], estado="ejecutando", razon_pausa=None)
    return jsonify({"ok": True})
