"""Frenos y heurísticas de seguridad para el loop autónomo."""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass

from ..ai import propuestas as prop_mod
from ..files.project import Proyecto


log = logging.getLogger("novela_app.autonomo.frenos")


@dataclass
class EvaluacionFrenos:
    pausar: bool = False
    estado: str = "ejecutando"
    razon: str | None = None


CAPS_CERRADOS = {"revisado", "cerrado"}


def evaluar_frenos(
    *,
    proyecto: Proyecto,
    ejecucion: dict,
    tool_calls: list[dict],
    propuestas_nuevas_count: int,
    coste_paso: float,
) -> EvaluacionFrenos:
    # 1. Stuck: mismas tool calls que el paso anterior.
    firma_actual = _firma(tool_calls)
    firma_anterior = ejecucion.get("firma_ultimas_tools") or ""
    pasos = ejecucion.get("pasos_ejecutados") or 0
    if firma_actual and firma_actual == firma_anterior and pasos >= 1:
        return EvaluacionFrenos(
            pausar=True,
            estado="error_stuck",
            razon="Dos pasos consecutivos con tool calls idénticas. Posible bucle.",
        )

    # 2. Paso sin actividad: 0 propuestas, 0 tool calls.
    if propuestas_nuevas_count == 0 and not tool_calls and coste_paso > 0:
        # Si gastó tokens pero no produjo nada ni leyó nada, probablemente solo texto.
        # No pausamos todavía; lo marcamos para vigilar en el próximo paso.
        pass

    # 3. Cambios estructurales grandes sin confirmación.
    riesgos = _detectar_cambios_de_alto_riesgo(proyecto, tool_calls)
    if riesgos:
        return EvaluacionFrenos(
            pausar=True,
            estado="esperando_revision",
            razon=f"Cambios estructurales de alto riesgo detectados: {', '.join(riesgos)}. Revisa antes de seguir.",
        )

    # 4. Capítulos cerrados/revisados afectados.
    caps_afectados = _caps_cerrados_afectados(proyecto, tool_calls)
    if caps_afectados:
        return EvaluacionFrenos(
            pausar=True,
            estado="esperando_revision",
            razon=f"Propuesta sobre capítulo cerrado/revisado: {', '.join(caps_afectados)}. Aprobación humana obligatoria.",
        )

    return EvaluacionFrenos(pausar=False)


RUTAS_ESTRUCTURALES = {
    "03_estructura/actos.md",
    "03_estructura/escaleta.md",
    "03_estructura/cronologia.md",
    "03_estructura/pov.md",
    "00_concepto/premisa.md",
    "00_concepto/sinopsis.md",
    "00_concepto/tesis.md",
}


def _detectar_cambios_de_alto_riesgo(proyecto: Proyecto, tool_calls: list[dict]) -> list[str]:
    riesgos: list[str] = []
    for tc in tool_calls:
        if tc.get("name") != "modificar_fichero":
            continue
        ruta = (tc.get("input") or {}).get("ruta") or ""
        if ruta in RUTAS_ESTRUCTURALES:
            # Tamaño del diff: si el contenido nuevo difiere en > 50% del anterior, es alto riesgo.
            contenido_nuevo = (tc.get("input") or {}).get("contenido_nuevo") or ""
            try:
                abs_path = proyecto.ruta / ruta
                if abs_path.exists():
                    contenido_anterior = abs_path.read_text(encoding="utf-8")
                    if _ratio_cambio(contenido_anterior, contenido_nuevo) > 0.5:
                        riesgos.append(ruta)
            except OSError:
                continue
    return riesgos


def _ratio_cambio(a: str, b: str) -> float:
    import difflib

    if not a:
        return 1.0
    sm = difflib.SequenceMatcher(None, a, b)
    return 1.0 - sm.ratio()


def _caps_cerrados_afectados(proyecto: Proyecto, tool_calls: list[dict]) -> list[str]:
    from ..files.parser import parse_fichero

    afectados: list[str] = []
    for tc in tool_calls:
        if tc.get("name") != "modificar_fichero":
            continue
        ruta = (tc.get("input") or {}).get("ruta") or ""
        if not ruta.startswith("04_capitulos/"):
            continue
        abs_path = proyecto.ruta / ruta
        if not abs_path.exists():
            continue
        try:
            parsed = parse_fichero(abs_path)
            estado = (parsed["metadata"] or {}).get("estado")
            if estado in CAPS_CERRADOS:
                afectados.append(ruta)
        except Exception:
            continue
    return afectados


def _firma(tool_calls: list[dict]) -> str:
    if not tool_calls:
        return ""
    clave = "|".join(
        f"{t.get('name')}:{json.dumps(t.get('input') or {}, sort_keys=True)}"
        for t in tool_calls
    )
    return hashlib.sha256(clave.encode("utf-8")).hexdigest()[:16]
