"""Localización, creación y lectura de proyectos."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..config import Config
from .parser import SlugInvalidoError, escribir_fichero, escribir_raw, parse_fichero, validar_slug


CARPETAS_TITULOS = {
    "00_concepto": "Concepto",
    "01_personajes": "Personajes",
    "02_mundo": "Mundo",
    "03_estructura": "Estructura",
    "04_capitulos": "Capítulos",
    "05_control": "Control",
    "06_revision": "Revisión",
    "07_investigacion": "Investigación",
}

# Orden estable de las carpetas en el árbol.
CARPETAS_ORDEN = list(CARPETAS_TITULOS.keys())


@dataclass
class Proyecto:
    slug: str
    nombre: str
    tipo: str  # "novela" | "libro"
    ruta: Path
    config: dict
    canon_ruta: Path | None = None  # Solo para libros de saga.
    saga_slug: str | None = None

    @property
    def orden_path(self) -> Path:
        return self.ruta / "03_estructura" / "orden.json"


class ProyectoNoEncontrado(LookupError):
    pass


def _leer_json(ruta: Path) -> dict | None:
    if not ruta.exists():
        return None
    with ruta.open("r", encoding="utf-8") as f:
        return json.load(f)


def _escribir_json_atomico(ruta: Path, data: dict) -> None:
    escribir_raw(ruta, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def listar_proyectos() -> dict:
    """Devuelve {independientes: [...], sagas: [...]} según la spec 5.5."""
    indep_dir = Config.NOVELAS_ROOT / "independientes"
    sagas_dir = Config.NOVELAS_ROOT / "sagas"
    independientes: list[dict] = []
    sagas: list[dict] = []

    if indep_dir.exists():
        for p in sorted(indep_dir.iterdir()):
            if not p.is_dir():
                continue
            cfg = _leer_json(p / ".novela-config.json") or {}
            independientes.append(
                {
                    "slug": cfg.get("slug", p.name),
                    "nombre": cfg.get("nombre", p.name),
                    "ruta": f"independientes/{p.name}",
                }
            )

    if sagas_dir.exists():
        for p in sorted(sagas_dir.iterdir()):
            if not p.is_dir():
                continue
            cfg = _leer_json(p / ".saga-config.json") or {}
            sagas.append(
                {
                    "slug": cfg.get("slug", p.name),
                    "nombre": cfg.get("nombre", p.name),
                    "libros": cfg.get("libros", []),
                }
            )

    return {"independientes": independientes, "sagas": sagas}


def cargar_proyecto(slug: str) -> Proyecto:
    """Busca el proyecto por slug.

    Para independientes: slug simple (ej. "chari").
    Para libros de saga: slug compuesto "saga/libro" o "saga::libro".
    El segundo se usa en URLs para evitar choques con el routing de Flask.
    """
    slug = slug.replace("::", "/")
    if "/" in slug:
        saga_slug, libro_slug = slug.split("/", 1)
        saga_dir = Config.NOVELAS_ROOT / "sagas" / saga_slug
        if not saga_dir.exists():
            raise ProyectoNoEncontrado(f"Saga '{saga_slug}' no encontrada.")
        libro_dir = saga_dir / libro_slug
        if not libro_dir.exists() or not libro_dir.is_dir():
            raise ProyectoNoEncontrado(f"Libro '{libro_slug}' no encontrado en saga '{saga_slug}'.")
        cfg_libro = _leer_json(libro_dir / ".libro-config.json") or {}
        return Proyecto(
            slug=f"{saga_slug}/{libro_slug}",
            nombre=cfg_libro.get("nombre", libro_slug),
            tipo="libro",
            ruta=libro_dir,
            config=cfg_libro,
            canon_ruta=saga_dir / "00_canon_compartido",
            saga_slug=saga_slug,
        )

    # Independiente
    indep_dir = Config.NOVELAS_ROOT / "independientes"
    if indep_dir.exists():
        for p in indep_dir.iterdir():
            if not p.is_dir():
                continue
            cfg = _leer_json(p / ".novela-config.json") or {}
            if cfg.get("slug") == slug or p.name == slug:
                return Proyecto(
                    slug=cfg.get("slug", p.name),
                    nombre=cfg.get("nombre", p.name),
                    tipo="novela",
                    ruta=p,
                    config=cfg,
                )
    raise ProyectoNoEncontrado(f"Proyecto '{slug}' no encontrado.")


def numerar_capitulos(orden: dict) -> dict[str, str]:
    """Devuelve {slug: etiqueta_ui} a partir del orden.json."""
    etiquetas: dict[str, str] = {}
    prologo = orden.get("prologo")
    if prologo and prologo.get("slug"):
        etiquetas[prologo["slug"]] = prologo.get("etiqueta") or "Prólogo"
    for i, cap in enumerate(orden.get("capitulos") or [], start=1):
        slug = cap.get("slug") if isinstance(cap, dict) else cap
        if slug:
            etiquetas[slug] = f"Capítulo {i}"
    epilogo = orden.get("epilogo")
    if epilogo and epilogo.get("slug"):
        etiquetas[epilogo["slug"]] = epilogo.get("etiqueta") or "Epílogo"
    return etiquetas


def leer_orden(proyecto: Proyecto) -> dict:
    data = _leer_json(proyecto.orden_path)
    if data is None:
        return {"capitulos": []}
    return data


def escribir_orden(proyecto: Proyecto, orden: dict) -> None:
    _escribir_json_atomico(proyecto.orden_path, orden)


def _detectar_tipo_por_carpeta(carpeta: str) -> str:
    return {
        "04_capitulos": "capitulo",
        "01_personajes": "personaje",
        "02_mundo": "lugar",
    }.get(carpeta, "documento")


def construir_arbol(proyecto: Proyecto) -> dict:
    """Lee el árbol del proyecto y devuelve la estructura de la spec 5.5."""
    orden = leer_orden(proyecto)
    etiquetas = numerar_capitulos(orden)
    carpetas: list[dict] = []

    for carpeta in CARPETAS_ORDEN:
        dir_path = proyecto.ruta / carpeta
        if not dir_path.exists():
            continue
        ficheros: list[dict] = []
        for md in sorted(dir_path.glob("*.md")):
            try:
                parsed = parse_fichero(md)
            except Exception:
                parsed = {"metadata": {}, "content": "", "title": None}
            slug = md.stem
            tipo = _detectar_tipo_por_carpeta(carpeta)
            etiqueta_ui = etiquetas.get(slug) if tipo == "capitulo" else None
            ficheros.append(
                {
                    "slug": slug,
                    "ruta": f"{carpeta}/{md.name}",
                    "titulo": parsed["title"] or slug,
                    "etiqueta_ui": etiqueta_ui,
                    "tipo": tipo,
                    "metadata": parsed["metadata"],
                }
            )
        # Para capítulos, ordenar según orden.json (los no listados al final).
        if carpeta == "04_capitulos":
            orden_slugs = list(etiquetas.keys())
            def _clave(f):
                try:
                    return (0, orden_slugs.index(f["slug"]))
                except ValueError:
                    return (1, f["slug"])
            ficheros.sort(key=_clave)

        carpetas.append(
            {
                "nombre": carpeta,
                "titulo_humano": CARPETAS_TITULOS[carpeta],
                "ficheros": ficheros,
            }
        )

    return {"carpetas": carpetas}


# ---------------------------------------------------------------------------
# Creación de proyecto nuevo
# ---------------------------------------------------------------------------

def _plantillas_iniciales(slug: str, nombre: str) -> dict[str, tuple[dict | None, str]]:
    """Genera los ficheros base de un proyecto nuevo."""
    return {
        "00_concepto/premisa.md": (
            None,
            "# Premisa\n\nUna o dos frases: protagonista + objetivo + obstáculo + riesgo.\n",
        ),
        "00_concepto/sinopsis.md": (
            None,
            "# Sinopsis extendida\n\nResumen completo de la novela, con final incluido.\n",
        ),
        "00_concepto/tesis.md": (
            None,
            "# Tesis\n\n¿Qué trata la novela por debajo de la trama? Pregunta central y tensiones temáticas.\n",
        ),
        "03_estructura/actos.md": (
            None,
            "# Actos\n\nEsqueleto macro en 3/4/5 actos. Función, inicio y cierre de cada uno.\n",
        ),
        "03_estructura/escaleta.md": (
            None,
            "# Escaleta\n\nPlan capítulo a capítulo (5-15 líneas por capítulo).\n",
        ),
        "03_estructura/cronologia.md": (
            None,
            "# Cronología\n\nLínea temporal con fechas, edades y hechos previos.\n",
        ),
        "03_estructura/pov.md": (
            None,
            "# Puntos de vista\n\nQuién narra qué. Reglas de asignación.\n",
        ),
        "03_estructura/relaciones.md": (
            None,
            "# Grafo de relaciones\n\n## Por capítulo\n\n## Por personaje\n",
        ),
        "05_control/estilo.md": (
            None,
            "# Guía de estilo\n\nVoz, tiempo verbal, adjetivación, reglas de diálogo, lista negra.\n",
        ),
        "05_control/raccord.md": (
            None,
            "# Raccord\n\nDetalles que deben mantenerse coherentes entre capítulos.\n",
        ),
        "05_control/bitacora.md": (
            None,
            "# Bitácora de decisiones\n\nDecisión, razón, alternativas descartadas, fecha.\n",
        ),
        "02_mundo/worldbuilding.md": (
            None,
            "# Worldbuilding\n\nReglas del mundo que condicionan la trama.\n",
        ),
        "02_mundo/glosario.md": (
            None,
            "# Glosario\n\nTérminos propios, jerga, acrónimos.\n",
        ),
        "06_revision/plan_correcciones.md": (
            None,
            "# Plan de correcciones\n\nLista viva de problemas detectados, priorizados.\n",
        ),
        "06_revision/notas_editoriales.md": (
            None,
            "# Notas editoriales\n\nVeredicto tras lectura completa.\n",
        ),
        "07_investigacion/fuentes.md": (
            None,
            "# Fuentes\n\nReferencias consultadas.\n",
        ),
        "CLAUDE.md": (
            None,
            _plantilla_claude_md_proyecto(slug, nombre),
        ),
    }


def _plantilla_claude_md_proyecto(slug: str, nombre: str) -> str:
    return f"""# {nombre} — instrucciones para Claude Code

Este directorio es una novela del monorepo `gunovel`. Las reglas generales del dominio viven en `/CLAUDE.md` (raíz del repo); léelo si no lo has leído.

**Identificador del proyecto:** `{slug}`

## Estado inicial

Proyecto recién creado. Todos los ficheros tienen plantillas mínimas. Antes de redactar capítulos:

1. Completa con el autor: premisa, sinopsis con final incluido, tesis, estilo.
2. Crea biblia de personajes principales en `01_personajes/`.
3. Escribe worldbuilding mínimo si aplica.
4. Escribe al menos los actos y la escaleta hasta el final del primer acto.

Si el autor te pide trabajar en modo autónomo, crea `05_control/plan_autonomo.md` con las tareas pendientes y ve ejecutándolas una a una.

## Particularidades de este proyecto

(Añade aquí reglas específicas que el autor te vaya dando: tono particular, convenciones de nombre, personajes especialmente sensibles, pendientes, etc.)

## Tools MCP

Usa las tools del servidor `mcp__gunovel` pasándoles `proyecto_slug="{slug}"`.
"""


def crear_saga(slug: str, nombre: str) -> Path:
    """Crea la estructura base de una saga con canon compartido vacío."""
    validar_slug(slug)
    saga_dir = Config.NOVELAS_ROOT / "sagas" / slug
    if saga_dir.exists():
        raise FileExistsError(f"Ya existe una saga en {saga_dir}")

    canon = saga_dir / "00_canon_compartido"
    for sub in ("personajes", "mundo"):
        (canon / sub).mkdir(parents=True, exist_ok=True)

    plantillas_canon = {
        "cronologia_saga.md": "# Cronología de la saga\n\nLínea temporal global.\n",
        "reglas_universo.md": "# Reglas del universo\n\nLeyes físicas, sociales, tecnológicas compartidas.\n",
        "estilo.md": "# Guía de estilo (saga)\n\nVoz, reglas de prosa comunes a todos los libros.\n",
        "bitacora_saga.md": "# Bitácora de la saga\n\nDecisiones que afectan a toda la saga.\n",
    }
    for nombre_f, contenido in plantillas_canon.items():
        escribir_fichero(canon / nombre_f, None, contenido)

    cfg = {
        "tipo": "saga",
        "nombre": nombre,
        "slug": slug,
        "creado": datetime.now(timezone.utc).isoformat(),
        "libros": [],
        "modelo_por_defecto": Config.MODELO_POR_DEFECTO,
        "git": {"remoto_url": "", "auto_push": False},
    }
    _escribir_json_atomico(saga_dir / ".saga-config.json", cfg)

    escribir_raw(saga_dir / ".gitignore", ".DS_Store\nThumbs.db\n*.tmp\n")

    from ..versioning.git_ops import init_repo

    init_repo(saga_dir, autor_nombre=nombre, autor_email="autor@novela.local")

    return saga_dir


def añadir_libro_a_saga(saga_slug: str, libro_slug: str, libro_nombre: str, orden: int) -> Path:
    """Añade un libro nuevo a una saga existente. Usa el repo git de la saga."""
    validar_slug(libro_slug)
    saga_dir = Config.NOVELAS_ROOT / "sagas" / saga_slug
    if not saga_dir.exists():
        raise ProyectoNoEncontrado(f"Saga '{saga_slug}' no existe.")
    libro_dir = saga_dir / libro_slug
    if libro_dir.exists():
        raise FileExistsError(f"Ya existe un libro en {libro_dir}")

    for carpeta in CARPETAS_ORDEN:
        (libro_dir / carpeta).mkdir(parents=True, exist_ok=True)
    (libro_dir / "07_investigacion" / "referencias").mkdir(parents=True, exist_ok=True)

    # Plantillas iniciales — mismas que novela independiente.
    for ruta_rel, (meta, contenido) in _plantillas_iniciales(libro_slug, libro_nombre).items():
        escribir_fichero(libro_dir / ruta_rel, meta, contenido)
    _escribir_json_atomico(libro_dir / "03_estructura" / "orden.json", {"capitulos": []})

    cfg_libro = {
        "tipo": "libro",
        "nombre": libro_nombre,
        "slug": libro_slug,
        "numero_en_saga": orden,
        "estado": "borrador",
    }
    _escribir_json_atomico(libro_dir / ".libro-config.json", cfg_libro)

    # Actualizar .saga-config.json añadiendo el libro.
    saga_cfg_path = saga_dir / ".saga-config.json"
    saga_cfg = _leer_json(saga_cfg_path) or {}
    libros = saga_cfg.setdefault("libros", [])
    libros.append({"slug": libro_slug, "titulo": libro_nombre, "orden": orden})
    libros.sort(key=lambda x: x.get("orden") or 0)
    _escribir_json_atomico(saga_cfg_path, saga_cfg)

    from ..versioning.git_ops import commit_cambios

    commit_cambios(
        proyecto_ruta=saga_dir,
        mensaje=f"[SYS] Añadido libro '{libro_slug}' ({libro_nombre}) a la saga",
    )
    return libro_dir


def crear_proyecto_independiente(slug: str, nombre: str) -> Path:
    """Crea la estructura de una novela independiente. No inicializa git aquí.

    Git se inicializa desde la capa de versioning al terminar (devuelve el path
    para que el caller dispare la inicialización).
    """
    validar_slug(slug)
    ruta = Config.NOVELAS_ROOT / "independientes" / slug
    if ruta.exists():
        raise FileExistsError(f"Ya existe un proyecto en {ruta}")

    for carpeta in CARPETAS_ORDEN:
        (ruta / carpeta).mkdir(parents=True, exist_ok=True)
    (ruta / "07_investigacion" / "referencias").mkdir(parents=True, exist_ok=True)

    for ruta_rel, (meta, contenido) in _plantillas_iniciales(slug, nombre).items():
        escribir_fichero(ruta / ruta_rel, meta, contenido)

    # orden.json vacío
    _escribir_json_atomico(ruta / "03_estructura" / "orden.json", {"capitulos": []})

    # .novela-config.json
    cfg = {
        "tipo": "novela",
        "nombre": nombre,
        "slug": slug,
        "creado": datetime.now(timezone.utc).isoformat(),
        "modelo_por_defecto": Config.MODELO_POR_DEFECTO,
        "modelo_para_revision_editorial": Config.MODELO_OPUS,
        "estilo_resumen": "",
        "idioma": "es",
        "git": {"remoto_url": "", "auto_push": False},
    }
    _escribir_json_atomico(ruta / ".novela-config.json", cfg)

    # .gitignore del proyecto (no el de la app)
    escribir_raw(
        ruta / ".gitignore",
        ".DS_Store\nThumbs.db\n*.tmp\n",
    )

    # Inicializar git
    from ..versioning.git_ops import init_repo

    init_repo(ruta, autor_nombre=nombre, autor_email="autor@novela.local")

    return ruta
