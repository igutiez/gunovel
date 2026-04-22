"""Endpoints REST del chat IA y de aprobación de propuestas."""
from __future__ import annotations

from flask import Blueprint, abort, jsonify, request
from flask_login import login_required

from ..audit.db import (
    acumular_coste_conversacion,
    añadir_mensaje,
    conversaciones_de_proyecto,
    crear_conversacion,
    mensajes_de_conversacion,
    registrar_evento,
)
from ..files.parser import (
    RutaNoPermitidaError,
    escribir_raw,
    parse_fichero,
    ruta_segura,
)
from ..files.project import ProyectoNoEncontrado, cargar_proyecto, escribir_orden, leer_orden
from ..versioning.git_ops import commit_cambios
from . import propuestas as prop_mod
from .resumen import resumir_historial
from .tool_use import ejecutar_turno


bp = Blueprint("ai", __name__, url_prefix="/api")


def _cargar_o_404(slug: str):
    try:
        return cargar_proyecto(slug)
    except ProyectoNoEncontrado:
        abort(404, description=f"Proyecto '{slug}' no encontrado.")


@bp.get("/proyecto/<slug>/conversaciones")
@login_required
def api_conversaciones(slug: str):
    _cargar_o_404(slug)
    return jsonify({"conversaciones": conversaciones_de_proyecto(slug)})


@bp.get("/proyecto/<slug>/conversacion/<conv_id>")
@login_required
def api_ver_conversacion(slug: str, conv_id: str):
    _cargar_o_404(slug)
    return jsonify({"mensajes": mensajes_de_conversacion(conv_id)})


@bp.post("/proyecto/<slug>/chat")
@login_required
def api_chat(slug: str):
    proyecto = _cargar_o_404(slug)
    data = request.get_json(silent=True) or {}
    mensaje = (data.get("mensaje") or "").strip()
    if not mensaje:
        abort(400, description="Falta 'mensaje'.")
    ruta_activa = data.get("ruta_activa") or None
    conv_id = data.get("conversacion_id")
    modelo = data.get("modelo")

    if not conv_id:
        conv_id = crear_conversacion(slug, titulo=_titulo_corto(mensaje))

    historial_db = mensajes_de_conversacion(conv_id)
    historial_api = _historial_para_api(historial_db)

    añadir_mensaje(conv_id, "user", mensaje)

    resultado = ejecutar_turno(
        proyecto=proyecto,
        ruta_activa=ruta_activa,
        historial=historial_api,
        mensaje_usuario=mensaje,
        conversacion_id=conv_id,
        modelo=modelo,
    )

    if resultado.error:
        añadir_mensaje(conv_id, "assistant", f"[Error] {resultado.error}")
        return jsonify(
            {
                "ok": False,
                "conversacion_id": conv_id,
                "error": resultado.error,
            }
        ), 502

    añadir_mensaje(
        conv_id,
        "assistant",
        resultado.texto_final,
        tool_calls=resultado.tool_calls or None,
    )
    if resultado.coste_eur:
        acumular_coste_conversacion(conv_id, resultado.coste_eur)

    tipo_evento = "ia_escritura_propuesta" if resultado.propuestas else (
        "ia_lectura" if resultado.tool_calls else "ia_respuesta"
    )
    registrar_evento(
        tipo=tipo_evento,
        proyecto_slug=slug,
        conversacion_id=conv_id,
        mensaje_usuario=mensaje,
        tokens={
            "input": resultado.tokens_input,
            "cached": resultado.tokens_cache_read,
            "output": resultado.tokens_output,
        },
        modelo=modelo or proyecto.config.get("modelo_por_defecto"),
        tool_calls=resultado.tool_calls or None,
        coste_eur=resultado.coste_eur,
        resultado="truncado" if resultado.truncado_por_limite else "ok",
    )

    return jsonify(
        {
            "ok": True,
            "conversacion_id": conv_id,
            "respuesta": resultado.texto_final,
            "tool_calls": resultado.tool_calls,
            "propuestas": resultado.propuestas,
            "tokens": {
                "input": resultado.tokens_input,
                "cache_read": resultado.tokens_cache_read,
                "cache_write": resultado.tokens_cache_write,
                "output": resultado.tokens_output,
            },
            "coste_eur": resultado.coste_eur,
            "truncado_por_limite": resultado.truncado_por_limite,
        }
    )


# ---------------------------------------------------------------------------
# Aprobación / rechazo de propuestas
# ---------------------------------------------------------------------------

@bp.post("/proyecto/<slug>/propuesta/<propuesta_id>/aplicar")
@login_required
def api_aplicar(slug: str, propuesta_id: str):
    proyecto = _cargar_o_404(slug)
    prop = prop_mod.obtener(propuesta_id)
    if prop is None or prop.proyecto_slug != slug:
        abort(404, description="Propuesta no encontrada.")
    if prop.estado != "pendiente":
        abort(409, description=f"La propuesta ya está {prop.estado}.")

    data = request.get_json(silent=True) or {}
    contenido_override = data.get("contenido_nuevo")

    try:
        commit_hash = _aplicar_propuesta(proyecto, prop, contenido_override)
    except Exception as exc:  # noqa: BLE001
        registrar_evento(
            tipo="ia_escritura_rechazada",
            proyecto_slug=slug,
            fichero=prop.ruta,
            conversacion_id=prop.conversacion_id,
            motivo_ia=prop.motivo,
            resultado=f"error_al_aplicar: {exc}",
        )
        abort(500, description=str(exc))

    prop_mod.marcar(propuesta_id, "aplicada")
    registrar_evento(
        tipo="ia_escritura_aplicada",
        proyecto_slug=slug,
        fichero=prop.ruta,
        commit_git=commit_hash,
        conversacion_id=prop.conversacion_id,
        motivo_ia=prop.motivo,
        resultado="ok",
    )
    return jsonify({"ok": True, "commit": commit_hash, "propuesta_id": propuesta_id})


@bp.put("/proyecto/<slug>/propuesta/<propuesta_id>")
@login_required
def api_editar_propuesta(slug: str, propuesta_id: str):
    _cargar_o_404(slug)
    prop = prop_mod.obtener(propuesta_id)
    if prop is None or prop.proyecto_slug != slug:
        abort(404, description="Propuesta no encontrada.")
    if prop.estado != "pendiente":
        abort(409, description=f"La propuesta ya está {prop.estado}.")
    data = request.get_json(silent=True) or {}
    contenido_nuevo = data.get("contenido_nuevo")
    if contenido_nuevo is None:
        abort(400, description="Falta 'contenido_nuevo'.")
    if prop.tipo not in ("modificar_fichero", "crear_fichero"):
        abort(400, description="Sólo se pueden editar propuestas de fichero.")
    prop_mod.actualizar_contenido(propuesta_id, contenido_nuevo)
    prop = prop_mod.obtener(propuesta_id)
    return jsonify({"ok": True, "propuesta": prop_mod.serializar(prop)})


@bp.get("/proyecto/<slug>/propuestas")
@login_required
def api_listar_propuestas(slug: str):
    _cargar_o_404(slug)
    return jsonify(
        {
            "propuestas": [
                prop_mod.serializar(p)
                for p in prop_mod.listar_pendientes_proyecto(slug)
            ]
        }
    )


@bp.post("/proyecto/<slug>/propuesta/<propuesta_id>/rechazar")
@login_required
def api_rechazar(slug: str, propuesta_id: str):
    proyecto = _cargar_o_404(slug)
    prop = prop_mod.obtener(propuesta_id)
    if prop is None or prop.proyecto_slug != slug:
        abort(404, description="Propuesta no encontrada.")
    if prop.estado != "pendiente":
        abort(409, description=f"La propuesta ya está {prop.estado}.")

    prop_mod.marcar(propuesta_id, "rechazada")
    registrar_evento(
        tipo="ia_escritura_rechazada",
        proyecto_slug=slug,
        fichero=prop.ruta,
        conversacion_id=prop.conversacion_id,
        motivo_ia=prop.motivo,
        resultado="rechazada_por_usuario",
    )
    return jsonify({"ok": True, "propuesta_id": propuesta_id})


def _aplicar_propuesta(proyecto, prop, contenido_override: str | None) -> str | None:
    if prop.tipo in ("modificar_fichero", "crear_fichero"):
        try:
            abs_path = ruta_segura(proyecto.ruta, prop.ruta or "")
        except RutaNoPermitidaError as exc:
            raise RuntimeError(str(exc))
        contenido = contenido_override if contenido_override is not None else prop.contenido_nuevo
        if contenido is None:
            raise RuntimeError("Propuesta sin contenido.")
        if prop.tipo == "crear_fichero" and abs_path.exists():
            raise RuntimeError("El fichero ya existe, no se puede crear.")
        escribir_raw(abs_path, contenido if contenido.endswith("\n") else contenido + "\n")
        verbo = "crear" if prop.tipo == "crear_fichero" else "modificar"
        return commit_cambios(
            proyecto_ruta=proyecto.ruta,
            mensaje=f"[IA] {prop.ruta}: {prop.motivo}",
            paths=[prop.ruta],
        )

    if prop.tipo == "reordenar_capitulos":
        orden = leer_orden(proyecto)
        orden["capitulos"] = [{"slug": s} for s in (prop.nuevo_orden or [])]
        escribir_orden(proyecto, orden)
        return commit_cambios(
            proyecto_ruta=proyecto.ruta,
            mensaje=f"[IA] 03_estructura/orden.json: {prop.motivo}",
            paths=["03_estructura/orden.json"],
        )

    if prop.tipo == "actualizar_grafo_relaciones":
        from .grafo import aplicar_cambios_grafo

        ruta_rel = "03_estructura/relaciones.md"
        abs_path = proyecto.ruta / ruta_rel
        existente = abs_path.read_text(encoding="utf-8") if abs_path.exists() else "# Grafo de relaciones\n"
        nuevo = aplicar_cambios_grafo(existente, prop.cambios or [])
        escribir_raw(abs_path, nuevo)
        return commit_cambios(
            proyecto_ruta=proyecto.ruta,
            mensaje=f"[IA] {ruta_rel}: {prop.motivo}",
            paths=[ruta_rel],
        )

    raise RuntimeError(f"Tipo de propuesta desconocido: {prop.tipo}")


def _titulo_corto(mensaje: str) -> str:
    m = mensaje.strip().splitlines()[0]
    return m if len(m) <= 80 else m[:77] + "..."


def _historial_para_api(mensajes: list[dict]) -> list[dict]:
    from ..config import Config

    api: list[dict] = []
    for m in mensajes:
        if m["rol"] not in ("user", "assistant"):
            continue
        contenido = m["contenido"]
        if not contenido:
            continue
        api.append({"role": m["rol"], "content": contenido})

    ventana = Config.VENTANA_HISTORIAL_MENSAJES
    umbral = Config.UMBRAL_RESUMIR_HISTORIAL
    if len(api) <= ventana:
        return api

    # Resumimos los mensajes más antiguos que caen fuera de la ventana.
    antiguos = api[:-umbral]
    recientes = api[-umbral:]
    try:
        resumen = resumir_historial(antiguos)
    except Exception:
        resumen = "Resumen no disponible."
    prefijo = [{"role": "user", "content": f"[Resumen del historial previo]\n{resumen}"}]
    return prefijo + recientes
