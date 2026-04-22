"""Verificación de coherencia automática.

Chequeos baratos y deterministas que puede hacer la app sin llamar a la IA:
- Metadata: slugs en frontmatter coinciden con nombre de fichero, estados válidos.
- aparece_en de fichas de personajes/lugares apunta a capítulos existentes.
- Personajes declarados en `personajes:` de un capítulo tienen ficha correspondiente.
- Personajes que menciona el texto y no aparecen en la lista `personajes:` del capítulo.
- POV es un personaje con ficha.
- Orden del capítulo coincide con orden.json.

Devuelve lista de hallazgos, cada uno {tipo, gravedad, fichero, mensaje}.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..files.parser import parse_fichero
from ..files.project import Proyecto, leer_orden, numerar_capitulos


ESTADOS_CAPITULO_VALIDOS = {"esqueleto", "borrador", "borrador_v2", "revisado", "cerrado"}
ROLES_VALIDOS = {"principal", "secundario", "terciario", "mencionado"}


def verificar(proyecto: Proyecto, ambito: str) -> dict:
    """Ejecuta chequeos sobre un capítulo o sobre todo el proyecto."""
    hallazgos: list[dict] = []

    fichas_personajes = _cargar_fichas(proyecto, "01_personajes")
    fichas_lugares = _cargar_fichas(proyecto, "02_mundo")
    # En saga, incluir también canon.
    if proyecto.canon_ruta:
        fichas_personajes.update(_cargar_fichas_abs(proyecto.canon_ruta / "personajes"))
        fichas_lugares.update(_cargar_fichas_abs(proyecto.canon_ruta / "mundo"))

    slugs_personajes = set(fichas_personajes.keys())
    slugs_lugares = set(fichas_lugares.keys())

    orden = leer_orden(proyecto)
    etiquetas = numerar_capitulos(orden)
    slugs_capitulos_listados = set(etiquetas.keys())

    capitulos_a_revisar: list[str]
    if ambito == "proyecto":
        capitulos_a_revisar = sorted(slugs_capitulos_listados)
        # Chequeos de fichas sólo en ámbito global.
        hallazgos.extend(_revisar_fichas_personajes(fichas_personajes, slugs_capitulos_listados))
        hallazgos.extend(_revisar_fichas_lugares(fichas_lugares, slugs_capitulos_listados))
        hallazgos.extend(_revisar_capitulos_huerfanos(proyecto, slugs_capitulos_listados))
    else:
        capitulos_a_revisar = [ambito]

    for slug_cap in capitulos_a_revisar:
        hallazgos.extend(
            _revisar_capitulo(proyecto, slug_cap, slugs_personajes, slugs_lugares, etiquetas)
        )

    return {
        "ambito": ambito,
        "total_hallazgos": len(hallazgos),
        "hallazgos": hallazgos,
    }


def _cargar_fichas(proyecto: Proyecto, subcarpeta: str) -> dict[str, dict]:
    return _cargar_fichas_abs(proyecto.ruta / subcarpeta)


def _cargar_fichas_abs(dir_p: Path) -> dict[str, dict]:
    fichas: dict[str, dict] = {}
    if not dir_p.exists():
        return fichas
    for md in dir_p.glob("*.md"):
        try:
            parsed = parse_fichero(md)
        except Exception:
            continue
        slug = md.stem
        fichas[slug] = {
            "slug": slug,
            "metadata": parsed["metadata"] or {},
            "content": parsed["content"],
            "ruta": md,
        }
    return fichas


def _revisar_fichas_personajes(fichas: dict, capitulos_listados: set[str]) -> list[dict]:
    hallazgos: list[dict] = []
    for slug, f in fichas.items():
        meta = f["metadata"]
        if meta.get("slug") and meta["slug"] != slug:
            hallazgos.append({
                "tipo": "slug_incoherente",
                "gravedad": "alta",
                "fichero": f"01_personajes/{slug}.md",
                "mensaje": f"slug en cabecera ('{meta['slug']}') ≠ nombre de fichero ('{slug}').",
            })
        rol = meta.get("rol")
        if rol and rol not in ROLES_VALIDOS:
            hallazgos.append({
                "tipo": "rol_desconocido",
                "gravedad": "media",
                "fichero": f"01_personajes/{slug}.md",
                "mensaje": f"rol '{rol}' no es uno de {sorted(ROLES_VALIDOS)}.",
            })
        aparece = meta.get("aparece_en") or []
        if isinstance(aparece, list):
            for s in aparece:
                if s not in capitulos_listados:
                    hallazgos.append({
                        "tipo": "aparece_en_no_existe",
                        "gravedad": "media",
                        "fichero": f"01_personajes/{slug}.md",
                        "mensaje": f"aparece_en referencia al capítulo '{s}' que no está en orden.json.",
                    })
    return hallazgos


def _revisar_fichas_lugares(fichas: dict, capitulos_listados: set[str]) -> list[dict]:
    hallazgos: list[dict] = []
    for slug, f in fichas.items():
        if slug in ("worldbuilding", "glosario", "mapa"):
            continue
        meta = f["metadata"]
        aparece = meta.get("aparece_en") or []
        if isinstance(aparece, list):
            for s in aparece:
                if s not in capitulos_listados:
                    hallazgos.append({
                        "tipo": "aparece_en_no_existe",
                        "gravedad": "media",
                        "fichero": f"02_mundo/{slug}.md",
                        "mensaje": f"aparece_en referencia al capítulo '{s}' que no está en orden.json.",
                    })
    return hallazgos


def _revisar_capitulos_huerfanos(proyecto: Proyecto, capitulos_listados: set[str]) -> list[dict]:
    hallazgos: list[dict] = []
    dir_caps = proyecto.ruta / "04_capitulos"
    if not dir_caps.exists():
        return hallazgos
    for md in dir_caps.glob("*.md"):
        if md.stem not in capitulos_listados:
            hallazgos.append({
                "tipo": "capitulo_sin_orden",
                "gravedad": "baja",
                "fichero": f"04_capitulos/{md.name}",
                "mensaje": "Capítulo existe en disco pero no está en orden.json (no aparece numerado en la UI).",
            })
    return hallazgos


def _revisar_capitulo(
    proyecto: Proyecto,
    slug: str,
    slugs_personajes: set[str],
    slugs_lugares: set[str],
    etiquetas: dict[str, str],
) -> list[dict]:
    hallazgos: list[dict] = []
    md = proyecto.ruta / "04_capitulos" / f"{slug}.md"
    if not md.exists():
        hallazgos.append({
            "tipo": "capitulo_ausente",
            "gravedad": "alta",
            "fichero": f"04_capitulos/{slug}.md",
            "mensaje": "Capítulo listado en orden.json pero fichero no existe.",
        })
        return hallazgos
    try:
        parsed = parse_fichero(md)
    except Exception as exc:
        hallazgos.append({
            "tipo": "parse_error",
            "gravedad": "alta",
            "fichero": f"04_capitulos/{slug}.md",
            "mensaje": f"No se pudo parsear el frontmatter: {exc}",
        })
        return hallazgos

    meta = parsed["metadata"] or {}
    content = parsed["content"] or ""

    if meta.get("slug") and meta["slug"] != slug:
        hallazgos.append({
            "tipo": "slug_incoherente",
            "gravedad": "alta",
            "fichero": f"04_capitulos/{slug}.md",
            "mensaje": f"slug en cabecera ('{meta['slug']}') ≠ nombre de fichero ('{slug}').",
        })

    estado = meta.get("estado")
    if estado and estado not in ESTADOS_CAPITULO_VALIDOS:
        hallazgos.append({
            "tipo": "estado_desconocido",
            "gravedad": "media",
            "fichero": f"04_capitulos/{slug}.md",
            "mensaje": f"estado '{estado}' no es uno de {sorted(ESTADOS_CAPITULO_VALIDOS)}.",
        })

    personajes_cap = meta.get("personajes") or []
    if not isinstance(personajes_cap, list):
        hallazgos.append({
            "tipo": "personajes_malformado",
            "gravedad": "alta",
            "fichero": f"04_capitulos/{slug}.md",
            "mensaje": "'personajes' debe ser una lista de slugs.",
        })
        personajes_cap = []

    for p in personajes_cap:
        if p not in slugs_personajes:
            hallazgos.append({
                "tipo": "personaje_sin_ficha",
                "gravedad": "media",
                "fichero": f"04_capitulos/{slug}.md",
                "mensaje": f"Personaje '{p}' declarado en cabecera pero sin ficha en 01_personajes/.",
            })

    pov = meta.get("pov")
    if pov and pov not in slugs_personajes:
        hallazgos.append({
            "tipo": "pov_sin_ficha",
            "gravedad": "alta",
            "fichero": f"04_capitulos/{slug}.md",
            "mensaje": f"pov '{pov}' no tiene ficha en 01_personajes/.",
        })

    # Detectar personajes mencionados en texto que no están en la cabecera.
    # Estrategia barata: buscar el nombre-titular de cada ficha (primer "# Nombre").
    nombres_a_slug = _nombres_a_slug(proyecto)
    texto_plano = content.lower()
    mencionados = set()
    for nombre, slug_p in nombres_a_slug.items():
        if len(nombre) < 3:
            continue
        patron = re.compile(r"\b" + re.escape(nombre.lower()) + r"\b")
        if patron.search(texto_plano):
            mencionados.add(slug_p)
    faltantes = mencionados - set(personajes_cap)
    for f in faltantes:
        hallazgos.append({
            "tipo": "personaje_mencionado_no_declarado",
            "gravedad": "baja",
            "fichero": f"04_capitulos/{slug}.md",
            "mensaje": f"Texto menciona '{f}' pero no está en `personajes:` de la cabecera.",
        })

    return hallazgos


def _nombres_a_slug(proyecto: Proyecto) -> dict[str, str]:
    """Construye un mapa 'Nombre que aparece en fichas' -> slug."""
    mapa: dict[str, str] = {}
    dirs = [proyecto.ruta / "01_personajes"]
    if proyecto.canon_ruta:
        dirs.append(proyecto.canon_ruta / "personajes")
    for dir_p in dirs:
        if not dir_p.exists():
            continue
        for md in dir_p.glob("*.md"):
            try:
                parsed = parse_fichero(md)
            except Exception:
                continue
            titulo = parsed["title"]
            if not titulo:
                continue
            # Usar todas las palabras individuales del título que tengan >= 3 letras.
            for palabra in re.findall(r"[\wáéíóúüñÁÉÍÓÚÜÑ]+", titulo):
                if len(palabra) >= 3 and palabra[0].isupper():
                    mapa[palabra] = md.stem
    return mapa
