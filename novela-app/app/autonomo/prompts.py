"""Mensaje del orquestador para cada turno del loop autónomo."""
from __future__ import annotations

from pathlib import Path

from ..ai import propuestas as prop_mod
from ..files.project import Proyecto
from . import db as autodb


FASES = {
    "concepcion": "Concepción: premisa, sinopsis, tesis, tono, referentes.",
    "estructura": "Estructura: actos, escaleta, cronología, POV, relaciones.",
    "personajes": "Personajes: biblia de personajes principales y secundarios, relaciones.",
    "mundo": "Mundo: worldbuilding, glosario, lugares relevantes.",
    "redaccion": "Redacción: capítulos según escaleta, respetando canon y voz.",
    "revision": "Revisión: auditoría, coherencia, pase editorial, raccord.",
    "todo": "Pipeline completo: concepción → estructura → personajes → mundo → redacción → revisión.",
}


def construir_mensaje_orquestador(proyecto: Proyecto, ejecucion: dict) -> str:
    """Instrucción del turno. Encabeza con estado y recuerda reglas."""
    plan_actual = _leer_plan(proyecto)
    preguntas_respondidas = _texto_respuestas(ejecucion["id"])
    propuestas_cola = len(prop_mod.listar_pendientes_proyecto(proyecto.slug))

    fase_desc = FASES.get(ejecucion["fase"], ejecucion["fase"])
    presupuesto = ejecucion["presupuesto_eur"]
    coste = ejecucion["coste_acumulado_eur"]
    restante = max(0.0, presupuesto - coste)

    plan_bloque = plan_actual or "(No hay plan todavía en 05_control/plan_autonomo.md. Tu primera tarea es crearlo.)"

    respuestas_bloque = (
        f"\n\n## Respuestas del autor a tus preguntas previas\n{preguntas_respondidas}"
        if preguntas_respondidas
        else ""
    )

    return f"""[ORQUESTADOR AUTÓNOMO · paso {ejecucion['pasos_ejecutados'] + 1}]

Estás en modo autónomo. Objetivo de esta ejecución: **{fase_desc}**

## Estado actual

- Coste acumulado: {coste:.4f} € / presupuesto {presupuesto:.2f} € (restan {restante:.2f} €).
- Propuestas pendientes de aprobación humana: {propuestas_cola} (tope {ejecucion['max_propuestas_cola']}).
- Pasos ejecutados hasta ahora: {ejecucion['pasos_ejecutados']}.

## Plan actual (05_control/plan_autonomo.md)

{plan_bloque}
{respuestas_bloque}

## Reglas INNEGOCIABLES de este turno

1. **Un solo paso por turno.** Haz UNA tarea del plan. No intentes varias a la vez.
2. **Siempre empieza leyendo el plan** con `leer_fichero('05_control/plan_autonomo.md')` (aunque te lo pegue arriba, vuelve a leerlo por si cambió). Si no existe, tu primera tarea es crearlo.
3. **Actualiza el plan** al final del turno con `modificar_fichero` marcando la tarea como `[x]` (hecha), `[?]` (pendiente de decisión del autor) o `[!]` (bloqueada por error).
4. **Si necesitas una decisión humana** (nombre, giro fuerte, ambigüedad canónica), NO la inventes. Añade la pregunta al fichero `05_control/preguntas_autor.md` con el formato especificado al final. La app detectará la nueva pregunta y pausará el loop hasta que el autor responda.
5. **No toques capítulos con estado `revisado` o `cerrado`** salvo emergencia canónica: para esos, añade una tarea en `06_revision/plan_correcciones.md` en su lugar.
6. **Respeta la voz del autor**: si existe `05_control/golden_reference.md`, úsalo como referencia antes de redactar prosa. Si existe `05_control/feedback_autor.md`, léelo — contiene correcciones previas que NO debes repetir.
7. **Tras redactar un capítulo**, usa `auditar_capitulo(slug)` sobre él y, si hay hallazgos graves (dicendi > 50% color, coherencia con gravedad alta, repeticiones >= 5), corrige con `modificar_fichero` en el MISMO turno antes de marcar la tarea como hecha.
8. **Tope de 3 propuestas de escritura por turno** (sin contar la del propio plan). Si tu tarea requiere más, divídela en varios turnos.
9. **Budget**: si estimas que el siguiente paso excede el presupuesto restante, NO lo inicies. Actualiza el plan con una nota y emite `[FASE_COMPLETADA]`.
10. **Termina el turno con un resumen breve de 2-3 líneas** de qué has hecho y qué toca después.
11. **Cuando el plan esté completamente marcado `[x]`** y no queden pendientes, responde con la línea literal `[FASE_COMPLETADA]` al final de tu mensaje.

## Formato de preguntas al autor

Si necesitas registrar una pregunta, añádela al final de `05_control/preguntas_autor.md` con este bloque exacto:

```
## [{{timestamp-ISO}}] {{prioridad: alta|normal|baja}}

**Pregunta:** {{texto de la pregunta}}

**Contexto:** {{por qué necesitas saber esto}}

**Propuesta por defecto (si el autor no responde):** {{opción que tomarías si te forzaran a decidir}}

**RESPUESTA:** _(el autor rellena aquí)_

---
```

La app detectará preguntas con `**RESPUESTA:**` vacía y pausará. NO avances mientras haya preguntas sin respuesta.

## Formato de tareas en el plan

Usa esta estructura exacta en `05_control/plan_autonomo.md`:

```
# Plan autónomo

## Fase: <nombre>

- [ ] Tarea pendiente
- [x] Tarea completada
- [?] Tarea bloqueada por pregunta (id: <pregunta_id si existe>)
- [!] Tarea con error: <motivo>

## Observaciones

(Lo que quieras anotar para el siguiente turno.)
```

Procede ahora con UNA tarea del plan (o crea el plan si no existe).
"""


def _leer_plan(proyecto: Proyecto) -> str:
    ruta = proyecto.ruta / "05_control" / "plan_autonomo.md"
    if not ruta.exists():
        return ""
    try:
        return ruta.read_text(encoding="utf-8")
    except OSError:
        return ""


def _texto_respuestas(ejecucion_id: str) -> str:
    preguntas = autodb.preguntas_de_ejecucion(ejecucion_id, solo_nuevas=False)
    respondidas_recientes = [p for p in preguntas if p.get("respuesta")]
    if not respondidas_recientes:
        return ""
    bloques: list[str] = []
    for p in respondidas_recientes[-10:]:
        bloques.append(
            f"**Pregunta (id {p['id'][:8]}):** {p['pregunta']}\n"
            f"**Respuesta del autor:** {p['respuesta']}"
        )
    return "\n\n".join(bloques)
