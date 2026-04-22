"""Herramientas (tool use) expuestas a la IA.

Solo-lectura: se ejecutan inmediatamente y devuelven datos a la IA.
Escritura: se registran como *propuestas* pendientes de aprobación humana;
la herramienta devuelve un ACK con el id de la propuesta.
"""
from __future__ import annotations

from pathlib import Path

from ..files.parser import RutaNoPermitidaError, parse_fichero, ruta_segura
from ..files.project import Proyecto, leer_orden, numerar_capitulos
from . import propuestas as prop_mod


# Schemas en el formato que espera la API de Anthropic.
TOOL_SCHEMAS: list[dict] = [
    {
        "name": "leer_fichero",
        "description": "Lee un fichero del proyecto activo. Devuelve metadata, título y contenido.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ruta": {
                    "type": "string",
                    "description": "Ruta relativa al proyecto, p.ej. '04_capitulos/jose_luis.md'.",
                }
            },
            "required": ["ruta"],
        },
    },
    {
        "name": "listar_ficheros_proyecto",
        "description": "Lista ficheros del proyecto, opcionalmente filtrando por subcarpeta.",
        "input_schema": {
            "type": "object",
            "properties": {
                "subcarpeta": {
                    "type": "string",
                    "description": "Subcarpeta opcional, p.ej. '01_personajes'.",
                }
            },
        },
    },
    {
        "name": "buscar_texto",
        "description": "Búsqueda de texto literal dentro del proyecto activo. Devuelve matches con ruta, línea y contexto.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "subcarpeta": {"type": "string"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "consultar_grafo_relaciones",
        "description": "Lee 03_estructura/relaciones.md. Si se pasa 'entidad', filtra por secciones que la mencionan.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entidad": {"type": "string"},
            },
        },
    },
    {
        "name": "obtener_info_capitulo",
        "description": "Devuelve info calculada sobre un capítulo: título, posición, etiqueta_ui, anterior, siguiente, personajes, pov.",
        "input_schema": {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
            },
            "required": ["slug"],
        },
    },
    {
        "name": "verificar_coherencia",
        "description": "Verifica coherencia sobre un ámbito dado. Devuelve lista de posibles incoherencias detectadas automáticamente (metadata, cronología, raccord).",
        "input_schema": {
            "type": "object",
            "properties": {
                "ambito": {"type": "string", "description": "'proyecto' o un slug de capítulo."},
            },
            "required": ["ambito"],
        },
    },
    {
        "name": "resumen_canon_actual",
        "description": (
            "Devuelve un resumen compacto del canon del proyecto: premisa en una "
            "frase, sinopsis en 3-4 líneas, lista de personajes principales con "
            "una línea cada uno, lugares principales, último capítulo aplicado y "
            "slug del siguiente según orden.json. Úsalo al inicio de un turno "
            "autónomo para no tener que leer 20 ficheros por separado."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "ver_capitulos_adyacentes",
        "description": (
            "Devuelve el capítulo anterior completo y la entrada de escaleta del "
            "siguiente (si existe), dado un slug de capítulo. Útil para mantener "
            "cohesión narrativa al redactar."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"slug": {"type": "string"}},
            "required": ["slug"],
        },
    },
    {
        "name": "auditar_capitulo",
        "description": (
            "Ejecuta auditoría editorial determinista (sin IA) sobre un capítulo "
            "o todo el proyecto. Detecta repeticiones de palabras y n-gramas, "
            "tics/muletillas configurables, verbos dicendi (dijo vs color), "
            "mezcla de tiempos verbales, erratas tipográficas, longitud fuera "
            "de rango, cronología y coherencia de metadata. Devuelve métricas "
            "y hallazgos; tú decides qué significa cada uno. Para auditoría "
            "completa del libro pasa slug = 'proyecto'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "slug": {
                    "type": "string",
                    "description": "Slug del capítulo (ej. 'jose_luis'), o 'proyecto' para todo el libro.",
                },
                "categorias": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Subset de ['repeticiones_palabra','repeticiones_ngrama',"
                        "'tics','dicendi','tiempos','erratas','longitud',"
                        "'cronologia','coherencia']. Omitir para ejecutar todas."
                    ),
                },
            },
            "required": ["slug"],
        },
    },
    {
        "name": "leer_canon_saga",
        "description": "Si el proyecto es un libro de saga, lee un fichero del canon compartido (rutas bajo 00_canon_compartido/). Falla si el proyecto no pertenece a una saga.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ruta": {"type": "string", "description": "Ruta relativa al canon, p.ej. 'personajes/elena.md'."},
            },
            "required": ["ruta"],
        },
    },
    # --- Escritura: registran propuesta, NO escriben en disco ---
    {
        "name": "modificar_fichero",
        "description": (
            "Propone una modificación a un fichero existente. NO escribe en disco: "
            "registra una propuesta que el autor aprobará o rechazará tras ver el diff. "
            "Requiere motivo breve (una frase)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ruta": {"type": "string", "description": "Ruta relativa al proyecto."},
                "contenido_nuevo": {
                    "type": "string",
                    "description": "Contenido completo que reemplazará al actual (no diff, no parche).",
                },
                "motivo": {"type": "string", "description": "Una frase explicando el cambio."},
            },
            "required": ["ruta", "contenido_nuevo", "motivo"],
        },
    },
    {
        "name": "crear_fichero",
        "description": (
            "Propone crear un fichero nuevo. Falla si la ruta ya existe. "
            "NO escribe en disco: registra propuesta. Requiere motivo."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ruta": {"type": "string"},
                "contenido": {"type": "string"},
                "motivo": {"type": "string"},
            },
            "required": ["ruta", "contenido", "motivo"],
        },
    },
    {
        "name": "reordenar_capitulos",
        "description": (
            "Propone un nuevo orden para los capítulos (lista de slugs). "
            "NO modifica orden.json: registra propuesta para aprobación."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nuevo_orden": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Lista de slugs en el orden deseado.",
                },
                "motivo": {"type": "string"},
            },
            "required": ["nuevo_orden", "motivo"],
        },
    },
    {
        "name": "actualizar_grafo_relaciones",
        "description": (
            "Propone modificaciones al grafo de relaciones (03_estructura/relaciones.md). "
            "Para cada cambio indica 'accion' (añadir|modificar|eliminar), la sección afectada "
            "y el texto. NO escribe: registra propuesta."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "cambios": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "accion": {"type": "string"},
                            "seccion": {"type": "string"},
                            "texto": {"type": "string"},
                        },
                        "required": ["accion", "seccion", "texto"],
                    },
                },
                "motivo": {"type": "string"},
            },
            "required": ["cambios", "motivo"],
        },
    },
]


# ---------------------------------------------------------------------------
# Ejecutores
# ---------------------------------------------------------------------------

class ToolError(Exception):
    pass


def ejecutar_tool(
    nombre: str,
    args: dict,
    proyecto: Proyecto,
    conversacion_id: str | None = None,
) -> dict:
    try:
        fn = _HANDLERS[nombre]
    except KeyError as exc:
        raise ToolError(f"Herramienta desconocida: {nombre}") from exc
    if nombre in _HANDLERS_ESCRITURA:
        return fn(args, proyecto, conversacion_id)
    return fn(args, proyecto)


def _tool_leer_fichero(args: dict, proyecto: Proyecto) -> dict:
    ruta_rel = args.get("ruta", "")
    try:
        abs_path = ruta_segura(proyecto.ruta, ruta_rel)
    except RutaNoPermitidaError as exc:
        raise ToolError(str(exc))
    if not abs_path.exists() or not abs_path.is_file():
        raise ToolError(f"No existe: {ruta_rel}")
    parsed = parse_fichero(abs_path)
    return {
        "ruta": ruta_rel,
        "metadata": parsed["metadata"],
        "title": parsed["title"],
        "content": parsed["content"],
    }


def _tool_listar(args: dict, proyecto: Proyecto) -> dict:
    subcarpeta = (args.get("subcarpeta") or "").strip()
    base = proyecto.ruta
    if subcarpeta:
        try:
            target = ruta_segura(base, subcarpeta)
        except RutaNoPermitidaError as exc:
            raise ToolError(str(exc))
        if not target.exists():
            raise ToolError(f"No existe: {subcarpeta}")
    else:
        target = base

    resultados: list[dict] = []
    for p in sorted(target.rglob("*.md")):
        rel = p.relative_to(base).as_posix()
        if rel.startswith(".git/"):
            continue
        resultados.append({"ruta": rel, "slug": p.stem})
    return {"ficheros": resultados}


def _tool_buscar(args: dict, proyecto: Proyecto) -> dict:
    query = (args.get("query") or "").strip()
    if not query:
        raise ToolError("Falta 'query'.")
    subcarpeta = (args.get("subcarpeta") or "").strip()
    base = proyecto.ruta
    if subcarpeta:
        try:
            target = ruta_segura(base, subcarpeta)
        except RutaNoPermitidaError as exc:
            raise ToolError(str(exc))
    else:
        target = base

    matches: list[dict] = []
    q_lower = query.lower()
    for p in target.rglob("*.md"):
        rel = p.relative_to(base).as_posix()
        if rel.startswith(".git/"):
            continue
        try:
            with p.open("r", encoding="utf-8") as f:
                for i, linea in enumerate(f, start=1):
                    if q_lower in linea.lower():
                        matches.append(
                            {
                                "ruta": rel,
                                "linea": i,
                                "contexto": linea.rstrip("\n"),
                            }
                        )
                        if len(matches) >= 200:
                            break
        except OSError:
            continue
        if len(matches) >= 200:
            break
    return {"query": query, "matches": matches}


def _tool_grafo(args: dict, proyecto: Proyecto) -> dict:
    ruta = proyecto.ruta / "03_estructura" / "relaciones.md"
    if not ruta.exists():
        return {"contenido": "", "nota": "relaciones.md no existe todavía."}
    contenido = ruta.read_text(encoding="utf-8")
    entidad = (args.get("entidad") or "").strip()
    if entidad:
        # Filtrado burdo: líneas y secciones que mencionan la entidad.
        lineas: list[str] = []
        for linea in contenido.splitlines():
            if entidad.lower() in linea.lower():
                lineas.append(linea)
        return {"entidad": entidad, "lineas": lineas}
    return {"contenido": contenido}


def _tool_info_capitulo(args: dict, proyecto: Proyecto) -> dict:
    slug = args.get("slug", "")
    orden = leer_orden(proyecto)
    etiquetas = numerar_capitulos(orden)
    if slug not in etiquetas:
        raise ToolError(f"Capítulo '{slug}' no está en orden.json.")
    slugs_orden = list(etiquetas.keys())
    idx = slugs_orden.index(slug)
    anterior = slugs_orden[idx - 1] if idx > 0 else None
    siguiente = slugs_orden[idx + 1] if idx < len(slugs_orden) - 1 else None

    md_path = proyecto.ruta / "04_capitulos" / f"{slug}.md"
    metadata: dict = {}
    titulo = slug
    if md_path.exists():
        parsed = parse_fichero(md_path)
        metadata = parsed["metadata"]
        titulo = parsed["title"] or slug
    return {
        "slug": slug,
        "titulo": titulo,
        "etiqueta_ui": etiquetas[slug],
        "anterior": anterior,
        "siguiente": siguiente,
        "personajes": metadata.get("personajes", []),
        "pov": metadata.get("pov"),
        "estado": metadata.get("estado"),
    }


def _tool_verificar(args: dict, proyecto: Proyecto) -> dict:
    from .coherencia import verificar as _verificar

    ambito = args.get("ambito", "proyecto")
    return _verificar(proyecto, ambito)


def _tool_resumen_canon(args: dict, proyecto: Proyecto) -> dict:
    base = proyecto.ruta
    premisa = _leer_primera_linea(base / "00_concepto" / "premisa.md")
    sinopsis_full = _leer_plano(base / "00_concepto" / "sinopsis.md")
    sinopsis = "\n".join(sinopsis_full.splitlines()[:6]) if sinopsis_full else None

    personajes = []
    dir_p = base / "01_personajes"
    if dir_p.exists():
        for md in sorted(dir_p.glob("*.md")):
            try:
                parsed = parse_fichero(md)
            except Exception:
                continue
            rol = (parsed["metadata"] or {}).get("rol", "")
            if rol not in ("principal", "secundario"):
                continue
            personajes.append(
                {
                    "slug": md.stem,
                    "titulo": parsed["title"] or md.stem,
                    "rol": rol,
                    "pitch": _primera_linea_no_titulo(parsed["content"] or ""),
                }
            )

    lugares = []
    dir_l = base / "02_mundo"
    if dir_l.exists():
        for md in sorted(dir_l.glob("*.md")):
            if md.stem in ("worldbuilding", "glosario", "mapa"):
                continue
            try:
                parsed = parse_fichero(md)
            except Exception:
                continue
            lugares.append(
                {
                    "slug": md.stem,
                    "titulo": parsed["title"] or md.stem,
                    "pitch": _primera_linea_no_titulo(parsed["content"] or ""),
                }
            )

    orden = leer_orden(proyecto)
    etiquetas = numerar_capitulos(orden)
    slugs = list(etiquetas.keys())
    ultimo_redactado: str | None = None
    siguiente: str | None = None
    for s in reversed(slugs):
        md = base / "04_capitulos" / f"{s}.md"
        if not md.exists():
            continue
        try:
            parsed = parse_fichero(md)
        except Exception:
            continue
        estado = (parsed["metadata"] or {}).get("estado", "")
        if estado and estado != "esqueleto":
            ultimo_redactado = s
            idx = slugs.index(s)
            if idx + 1 < len(slugs):
                siguiente = slugs[idx + 1]
            break
    if ultimo_redactado is None and slugs:
        siguiente = slugs[0]

    return {
        "premisa": premisa,
        "sinopsis_resumen": sinopsis,
        "personajes_principales": personajes,
        "lugares_principales": lugares,
        "total_capitulos_en_orden": len(slugs),
        "ultimo_redactado": ultimo_redactado,
        "siguiente_a_redactar": siguiente,
        "tiene_canon_saga": bool(proyecto.canon_ruta),
    }


def _tool_capitulos_adyacentes(args: dict, proyecto: Proyecto) -> dict:
    slug = args.get("slug") or ""
    orden = leer_orden(proyecto)
    etiquetas = numerar_capitulos(orden)
    slugs = list(etiquetas.keys())
    if slug not in slugs:
        raise ToolError(f"Capítulo '{slug}' no está en orden.json.")
    idx = slugs.index(slug)
    anterior_slug = slugs[idx - 1] if idx > 0 else None
    siguiente_slug = slugs[idx + 1] if idx + 1 < len(slugs) else None

    def _cap_full(s: str | None):
        if s is None:
            return None
        md = proyecto.ruta / "04_capitulos" / f"{s}.md"
        if not md.exists():
            return {"slug": s, "existe": False}
        parsed = parse_fichero(md)
        return {
            "slug": s,
            "existe": True,
            "titulo": parsed["title"],
            "metadata": parsed["metadata"],
            "content": parsed["content"],
        }

    def _cap_escaleta(s: str | None):
        if s is None:
            return None
        escaleta = _leer_plano(proyecto.ruta / "03_estructura" / "escaleta.md")
        if not escaleta:
            return {"slug": s, "escaleta": None}
        # Localizar sección "### <slug>" o "## Cap NN"; fallback: devolver todo el cuerpo.
        pat = re.compile(rf"^#{{1,6}}\s+.*\b{re.escape(s)}\b.*$", re.MULTILINE | re.IGNORECASE)
        m = pat.search(escaleta)
        if not m:
            return {"slug": s, "escaleta": None}
        resto = escaleta[m.start():]
        fin = re.search(r"\n#{1,6}\s", resto[1:])
        bloque = resto[: (fin.start() + 1) if fin else len(resto)]
        return {"slug": s, "escaleta": bloque.strip()}

    return {
        "actual": _cap_escaleta(slug),
        "anterior": _cap_full(anterior_slug),
        "siguiente": _cap_escaleta(siguiente_slug),
    }


def _leer_primera_linea(ruta) -> str | None:
    if not ruta.exists():
        return None
    try:
        parsed = parse_fichero(ruta)
    except Exception:
        return None
    return _primera_linea_no_titulo(parsed["content"] or "")


def _leer_plano(ruta) -> str | None:
    if not ruta.exists():
        return None
    try:
        parsed = parse_fichero(ruta)
    except Exception:
        return None
    return parsed["content"]


def _primera_linea_no_titulo(contenido: str) -> str:
    import re as _re

    for linea in contenido.splitlines():
        l = linea.strip()
        if not l or l.startswith("#") or l.startswith("-"):
            continue
        return l if len(l) <= 180 else l[:177] + "..."
    return ""


import re  # noqa: E402


def _tool_auditar(args: dict, proyecto: Proyecto) -> dict:
    from .auditoria import auditar

    slug = args.get("slug", "proyecto")
    categorias = args.get("categorias") or None
    slug_param = None if slug in ("proyecto", "*", "") else slug
    return auditar(proyecto, slug=slug_param, categorias=categorias)


def _tool_leer_canon(args: dict, proyecto: Proyecto) -> dict:
    if not proyecto.canon_ruta:
        raise ToolError("Este proyecto no pertenece a una saga; no hay canon compartido.")
    ruta_rel = args.get("ruta", "")
    try:
        abs_path = ruta_segura(proyecto.canon_ruta, ruta_rel)
    except RutaNoPermitidaError as exc:
        raise ToolError(str(exc))
    if not abs_path.exists() or not abs_path.is_file():
        raise ToolError(f"No existe en canon: {ruta_rel}")
    parsed = parse_fichero(abs_path)
    return {
        "ruta": ruta_rel,
        "origen": "canon_saga",
        "metadata": parsed["metadata"],
        "title": parsed["title"],
        "content": parsed["content"],
    }


# ---------------------------------------------------------------------------
# Handlers de escritura: registran propuesta, no ejecutan
# ---------------------------------------------------------------------------

def _motivo_obligatorio(args: dict) -> str:
    motivo = (args.get("motivo") or "").strip()
    if not motivo:
        raise ToolError("El motivo es obligatorio (una frase explicando el cambio).")
    return motivo


def _tool_modificar_fichero(args: dict, proyecto: Proyecto, conversacion_id: str | None) -> dict:
    ruta_rel = args.get("ruta", "")
    contenido_nuevo = args.get("contenido_nuevo")
    motivo = _motivo_obligatorio(args)
    if contenido_nuevo is None:
        raise ToolError("Falta 'contenido_nuevo'.")
    try:
        abs_path = ruta_segura(proyecto.ruta, ruta_rel)
    except RutaNoPermitidaError as exc:
        raise ToolError(str(exc))
    if not abs_path.exists():
        raise ToolError(f"No existe: {ruta_rel}. Para ficheros nuevos usa crear_fichero.")

    contenido_anterior = abs_path.read_text(encoding="utf-8")
    pid = prop_mod.nuevo_id()
    prop_mod.registrar(
        prop_mod.Propuesta(
            id=pid,
            tipo="modificar_fichero",
            proyecto_slug=proyecto.slug,
            conversacion_id=conversacion_id,
            motivo=motivo,
            ruta=ruta_rel,
            contenido_nuevo=contenido_nuevo,
            contenido_anterior=contenido_anterior,
        )
    )
    return {
        "propuesta_id": pid,
        "estado": "pendiente_aprobacion",
        "mensaje": f"Propuesta registrada para modificar {ruta_rel}. El autor aprobará o rechazará tras ver el diff.",
    }


def _tool_crear_fichero(args: dict, proyecto: Proyecto, conversacion_id: str | None) -> dict:
    ruta_rel = args.get("ruta", "")
    contenido = args.get("contenido", "")
    motivo = _motivo_obligatorio(args)
    try:
        abs_path = ruta_segura(proyecto.ruta, ruta_rel)
    except RutaNoPermitidaError as exc:
        raise ToolError(str(exc))
    if abs_path.exists():
        raise ToolError(f"Ya existe: {ruta_rel}. Para modificar usa modificar_fichero.")
    if not ruta_rel.endswith(".md"):
        raise ToolError("Solo se pueden crear ficheros .md desde esta herramienta.")

    pid = prop_mod.nuevo_id()
    prop_mod.registrar(
        prop_mod.Propuesta(
            id=pid,
            tipo="crear_fichero",
            proyecto_slug=proyecto.slug,
            conversacion_id=conversacion_id,
            motivo=motivo,
            ruta=ruta_rel,
            contenido_nuevo=contenido,
            contenido_anterior=None,
        )
    )
    return {
        "propuesta_id": pid,
        "estado": "pendiente_aprobacion",
        "mensaje": f"Propuesta registrada para crear {ruta_rel}.",
    }


def _tool_reordenar(args: dict, proyecto: Proyecto, conversacion_id: str | None) -> dict:
    nuevo_orden = args.get("nuevo_orden") or []
    if not isinstance(nuevo_orden, list) or not all(isinstance(s, str) for s in nuevo_orden):
        raise ToolError("'nuevo_orden' debe ser una lista de slugs.")
    motivo = _motivo_obligatorio(args)
    orden = leer_orden(proyecto)
    orden_actual = [
        c.get("slug") if isinstance(c, dict) else c
        for c in (orden.get("capitulos") or [])
    ]
    pid = prop_mod.nuevo_id()
    prop_mod.registrar(
        prop_mod.Propuesta(
            id=pid,
            tipo="reordenar_capitulos",
            proyecto_slug=proyecto.slug,
            conversacion_id=conversacion_id,
            motivo=motivo,
            nuevo_orden=nuevo_orden,
            orden_anterior=orden_actual,
        )
    )
    return {
        "propuesta_id": pid,
        "estado": "pendiente_aprobacion",
        "mensaje": "Propuesta de reordenación registrada.",
    }


def _tool_actualizar_grafo(args: dict, proyecto: Proyecto, conversacion_id: str | None) -> dict:
    cambios = args.get("cambios") or []
    if not isinstance(cambios, list):
        raise ToolError("'cambios' debe ser una lista.")
    motivo = _motivo_obligatorio(args)
    pid = prop_mod.nuevo_id()
    prop_mod.registrar(
        prop_mod.Propuesta(
            id=pid,
            tipo="actualizar_grafo_relaciones",
            proyecto_slug=proyecto.slug,
            conversacion_id=conversacion_id,
            motivo=motivo,
            cambios=cambios,
        )
    )
    return {
        "propuesta_id": pid,
        "estado": "pendiente_aprobacion",
        "mensaje": "Propuesta de actualización del grafo registrada.",
    }


_HANDLERS = {
    "leer_fichero": _tool_leer_fichero,
    "listar_ficheros_proyecto": _tool_listar,
    "buscar_texto": _tool_buscar,
    "consultar_grafo_relaciones": _tool_grafo,
    "obtener_info_capitulo": _tool_info_capitulo,
    "verificar_coherencia": _tool_verificar,
    "resumen_canon_actual": _tool_resumen_canon,
    "ver_capitulos_adyacentes": _tool_capitulos_adyacentes,
    "auditar_capitulo": _tool_auditar,
    "leer_canon_saga": _tool_leer_canon,
    "modificar_fichero": _tool_modificar_fichero,
    "crear_fichero": _tool_crear_fichero,
    "reordenar_capitulos": _tool_reordenar,
    "actualizar_grafo_relaciones": _tool_actualizar_grafo,
}

_HANDLERS_ESCRITURA = {
    "modificar_fichero",
    "crear_fichero",
    "reordenar_capitulos",
    "actualizar_grafo_relaciones",
}
