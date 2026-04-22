"""MCP server local de gunovel.

Expone tools de dominio a Claude Code. No hace lectura/escritura genérica de
ficheros (Claude Code ya tiene Read/Write/Edit/Glob/Grep para eso); solo
operaciones que requieren lógica de la app (auditoría, coherencia, resumen
de canon, adyacentes, info de capítulo, lista de proyectos).

Se arranca por stdio. Claude Code lo configura desde `.mcp.json` del repo.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

# Permitir import de `app` cuando se ejecuta este fichero directo.
_THIS = Path(__file__).resolve()
_ROOT = _THIS.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from mcp.server.fastmcp import FastMCP  # noqa: E402

from app.ai import coherencia as coh_mod  # noqa: E402
from app.ai.auditoria import auditar as _auditar  # noqa: E402
from app.files.parser import parse_fichero  # noqa: E402
from app.files.project import (  # noqa: E402
    ProyectoNoEncontrado,
    cargar_proyecto,
    leer_orden,
    listar_proyectos as _listar_proyectos,
    numerar_capitulos,
)


logging.basicConfig(
    level=logging.INFO,
    format="[mcp-gunovel] %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("mcp-gunovel")


mcp = FastMCP("gunovel")


def _proy(slug: str):
    try:
        return cargar_proyecto(slug)
    except ProyectoNoEncontrado as exc:
        raise ValueError(str(exc))


@mcp.tool()
def listar_proyectos() -> dict:
    """Lista novelas independientes y sagas con sus libros.

    Devuelve: {'independientes': [{slug, nombre}], 'sagas': [{slug, nombre, libros: [...]}]}
    """
    return _listar_proyectos()


@mcp.tool()
def resumen_canon_actual(proyecto_slug: str) -> dict:
    """Resumen compacto del canon de un proyecto.

    Devuelve premisa, sinopsis recortada, personajes principales con una línea
    cada uno, lugares principales, total de capítulos en orden, último
    redactado, siguiente a redactar. Úsalo al inicio de una sesión para
    ubicarte sin leer 20 ficheros por separado.
    """
    p = _proy(proyecto_slug)
    base = p.ruta

    def _leer(path: Path):
        if not path.exists():
            return None
        try:
            return parse_fichero(path)
        except Exception:
            return None

    def _primera_linea_utilidad(contenido: str) -> str:
        for l in contenido.splitlines():
            ls = l.strip()
            if not ls or ls.startswith("#") or ls.startswith("-"):
                continue
            return ls if len(ls) <= 180 else ls[:177] + "..."
        return ""

    prem = _leer(base / "00_concepto" / "premisa.md")
    sino = _leer(base / "00_concepto" / "sinopsis.md")

    personajes = []
    dir_p = base / "01_personajes"
    if dir_p.exists():
        for md in sorted(dir_p.glob("*.md")):
            parsed = _leer(md)
            if not parsed:
                continue
            rol = (parsed["metadata"] or {}).get("rol", "")
            if rol not in ("principal", "secundario"):
                continue
            personajes.append(
                {
                    "slug": md.stem,
                    "titulo": parsed["title"] or md.stem,
                    "rol": rol,
                    "pitch": _primera_linea_utilidad(parsed["content"] or ""),
                }
            )

    lugares = []
    dir_l = base / "02_mundo"
    if dir_l.exists():
        for md in sorted(dir_l.glob("*.md")):
            if md.stem in ("worldbuilding", "glosario", "mapa"):
                continue
            parsed = _leer(md)
            if not parsed:
                continue
            lugares.append(
                {
                    "slug": md.stem,
                    "titulo": parsed["title"] or md.stem,
                    "pitch": _primera_linea_utilidad(parsed["content"] or ""),
                }
            )

    orden = leer_orden(p)
    etiquetas = numerar_capitulos(orden)
    slugs = list(etiquetas.keys())
    ultimo = None
    siguiente = None
    for s in reversed(slugs):
        md = base / "04_capitulos" / f"{s}.md"
        if not md.exists():
            continue
        parsed = _leer(md)
        if not parsed:
            continue
        estado = (parsed["metadata"] or {}).get("estado", "")
        if estado and estado != "esqueleto":
            ultimo = s
            idx = slugs.index(s)
            if idx + 1 < len(slugs):
                siguiente = slugs[idx + 1]
            break
    if ultimo is None and slugs:
        siguiente = slugs[0]

    return {
        "proyecto_slug": proyecto_slug,
        "ruta": str(p.ruta),
        "premisa": (prem["content"] if prem else None),
        "sinopsis_resumen": (
            "\n".join((sino["content"] or "").splitlines()[:6]) if sino else None
        ),
        "personajes_principales": personajes,
        "lugares_principales": lugares,
        "total_capitulos_en_orden": len(slugs),
        "ultimo_redactado": ultimo,
        "siguiente_a_redactar": siguiente,
        "tiene_canon_saga": bool(p.canon_ruta),
    }


@mcp.tool()
def obtener_info_capitulo(proyecto_slug: str, slug: str) -> dict:
    """Info calculada sobre un capítulo: título, etiqueta UI, posición, personajes, POV, estado, anterior y siguiente."""
    p = _proy(proyecto_slug)
    orden = leer_orden(p)
    etiquetas = numerar_capitulos(orden)
    if slug not in etiquetas:
        raise ValueError(f"Capítulo '{slug}' no está en orden.json.")
    slugs = list(etiquetas.keys())
    idx = slugs.index(slug)
    anterior = slugs[idx - 1] if idx > 0 else None
    siguiente = slugs[idx + 1] if idx < len(slugs) - 1 else None
    md = p.ruta / "04_capitulos" / f"{slug}.md"
    meta: dict = {}
    titulo = slug
    if md.exists():
        parsed = parse_fichero(md)
        meta = parsed["metadata"] or {}
        titulo = parsed["title"] or slug
    return {
        "slug": slug,
        "titulo": titulo,
        "etiqueta_ui": etiquetas[slug],
        "posicion": idx + 1,
        "anterior": anterior,
        "siguiente": siguiente,
        "personajes": meta.get("personajes", []),
        "pov": meta.get("pov"),
        "estado": meta.get("estado"),
    }


@mcp.tool()
def ver_capitulos_adyacentes(proyecto_slug: str, slug: str) -> dict:
    """Devuelve el capítulo anterior completo (prosa incluida) y la entrada de escaleta del siguiente.

    Útil para mantener cohesión narrativa al redactar. Pasa el slug del
    capítulo sobre el que vas a trabajar (no del anterior).
    """
    import re

    p = _proy(proyecto_slug)
    orden = leer_orden(p)
    etiquetas = numerar_capitulos(orden)
    slugs = list(etiquetas.keys())
    if slug not in slugs:
        raise ValueError(f"Capítulo '{slug}' no está en orden.json.")
    idx = slugs.index(slug)
    anterior_slug = slugs[idx - 1] if idx > 0 else None
    siguiente_slug = slugs[idx + 1] if idx + 1 < len(slugs) else None

    def _cap_full(s):
        if s is None:
            return None
        md = p.ruta / "04_capitulos" / f"{s}.md"
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

    def _cap_escaleta(s):
        if s is None:
            return None
        escaleta_path = p.ruta / "03_estructura" / "escaleta.md"
        if not escaleta_path.exists():
            return {"slug": s, "escaleta": None}
        contenido = escaleta_path.read_text(encoding="utf-8")
        pat = re.compile(rf"^#{{1,6}}\s+.*\b{re.escape(s)}\b.*$", re.MULTILINE | re.IGNORECASE)
        m = pat.search(contenido)
        if not m:
            return {"slug": s, "escaleta": None}
        resto = contenido[m.start():]
        fin = re.search(r"\n#{1,6}\s", resto[1:])
        bloque = resto[: (fin.start() + 1) if fin else len(resto)]
        return {"slug": s, "escaleta": bloque.strip()}

    return {
        "actual_escaleta": _cap_escaleta(slug),
        "anterior_completo": _cap_full(anterior_slug),
        "siguiente_escaleta": _cap_escaleta(siguiente_slug),
    }


@mcp.tool()
def verificar_coherencia(proyecto_slug: str, ambito: str = "proyecto") -> dict:
    """Chequeos deterministas de coherencia de canon.

    ambito: 'proyecto' para revisión global, o un slug de capítulo para uno concreto.
    Devuelve lista de hallazgos con tipo, gravedad y mensaje.
    """
    p = _proy(proyecto_slug)
    return coh_mod.verificar(p, ambito)


@mcp.tool()
def auditar_capitulo(
    proyecto_slug: str,
    slug: str = "proyecto",
    categorias: list[str] | None = None,
    minimo_palabras: int = 1500,
    maximo_palabras: int = 2500,
) -> dict:
    """Auditoría editorial determinista de un capítulo o de todo el proyecto.

    Devuelve métricas y hallazgos por categoría: repeticiones_palabra,
    repeticiones_ngrama, tics, dicendi, tiempos, erratas, longitud,
    cronologia, coherencia. slug='proyecto' para auditoría completa.
    """
    p = _proy(proyecto_slug)
    slug_param = None if slug in ("proyecto", "*", "") else slug
    return _auditar(
        p,
        slug=slug_param,
        categorias=categorias,
        minimo_palabras=minimo_palabras,
        maximo_palabras=maximo_palabras,
    )


if __name__ == "__main__":
    log.info("Arrancando MCP server gunovel sobre stdio")
    mcp.run()
