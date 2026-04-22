"""Ensamblado de contexto en tres capas.

Capa 1 (estable): premisa, tesis, sinopsis, estilo, lista de personajes, actos.
Capa 2 (semi-estable): escaleta, raccord, relaciones para fichero activo.
Capa 3 (variable): fichero activo actual y mensaje del usuario.

El system prompt lo compone prompts.componer_system_prompt, este módulo devuelve
los bloques de texto planos que se pegan a la conversación.
"""
from __future__ import annotations

from pathlib import Path

from ..files.parser import parse_fichero
from ..files.project import Proyecto


def _leer_si_existe(ruta: Path) -> str | None:
    if not ruta.exists() or not ruta.is_file():
        return None
    try:
        return parse_fichero(ruta)["content"].strip() or None
    except Exception:
        return None


def contexto_capa1(proyecto: Proyecto) -> dict:
    """Bloque estable del proyecto (incluye canon compartido si es libro de saga)."""
    base = proyecto.ruta
    estilo_libro = _leer_si_existe(base / "05_control" / "estilo.md")
    estilo_canon = None
    reglas_canon = None
    cronologia_canon = None
    if proyecto.canon_ruta:
        estilo_canon = _leer_si_existe(proyecto.canon_ruta / "estilo.md")
        reglas_canon = _leer_si_existe(proyecto.canon_ruta / "reglas_universo.md")
        cronologia_canon = _leer_si_existe(proyecto.canon_ruta / "cronologia_saga.md")

    # Combinamos estilo canon + estilo libro (canon primero).
    estilo_partes = []
    if estilo_canon:
        estilo_partes.append("### Estilo de la saga\n" + estilo_canon)
    if estilo_libro:
        estilo_partes.append("### Estilo de este libro\n" + estilo_libro)
    estilo = "\n\n".join(estilo_partes) if estilo_partes else None

    return {
        "premisa": _leer_si_existe(base / "00_concepto" / "premisa.md"),
        "tesis": _leer_si_existe(base / "00_concepto" / "tesis.md"),
        "sinopsis": _leer_si_existe(base / "00_concepto" / "sinopsis.md"),
        "estilo": estilo,
        "actos": _leer_si_existe(base / "03_estructura" / "actos.md"),
        "personajes_resumen": _resumen_personajes(proyecto),
        "reglas_universo": reglas_canon,
        "cronologia_saga": cronologia_canon,
    }


def _resumen_personajes(proyecto: Proyecto) -> str | None:
    """Una línea por personaje principal. Incluye canon de saga si aplica."""
    lineas: list[str] = []
    directorios: list[tuple[Path, str]] = []
    if proyecto.canon_ruta:
        directorios.append((proyecto.canon_ruta / "personajes", "saga"))
    directorios.append((proyecto.ruta / "01_personajes", "libro"))

    for dir_p, origen in directorios:
        if not dir_p.exists():
            continue
        for md in sorted(dir_p.glob("*.md")):
            try:
                parsed = parse_fichero(md)
            except Exception:
                continue
            rol = parsed["metadata"].get("rol", "")
            if rol and rol not in ("principal", "secundario"):
                continue
            titulo = parsed["title"] or md.stem
            primera_linea = _primera_linea_significativa(parsed["content"])
            marca = " [saga]" if origen == "saga" else ""
            resumen = f"- {titulo}{marca}"
            if rol:
                resumen += f" ({rol})"
            if primera_linea:
                resumen += f": {primera_linea}"
            lineas.append(resumen)
    return "\n".join(lineas) if lineas else None


def _primera_linea_significativa(contenido: str) -> str:
    for linea in contenido.splitlines():
        l = linea.strip()
        if not l or l.startswith("#") or l.startswith("-"):
            continue
        if len(l) > 200:
            return l[:197] + "..."
        return l
    return ""


def contexto_capa2(proyecto: Proyecto, ruta_activa: str | None) -> dict:
    """Bloque semi-estable: depende del fichero activo."""
    if not ruta_activa:
        return {}
    base = proyecto.ruta
    bloque: dict[str, str | None] = {}
    if ruta_activa.startswith("04_capitulos/"):
        bloque["escaleta"] = _leer_si_existe(base / "03_estructura" / "escaleta.md")
        bloque["raccord"] = _leer_si_existe(base / "05_control" / "raccord.md")
        bloque["relaciones"] = _leer_si_existe(base / "03_estructura" / "relaciones.md")
    elif ruta_activa.startswith("01_personajes/") or ruta_activa.startswith("02_mundo/"):
        bloque["relaciones"] = _leer_si_existe(base / "03_estructura" / "relaciones.md")
    return {k: v for k, v in bloque.items() if v}


def contexto_capa3(proyecto: Proyecto, ruta_activa: str | None) -> dict:
    """Bloque variable: fichero activo."""
    if not ruta_activa:
        return {}
    try:
        abs_path = proyecto.ruta / ruta_activa
        if not abs_path.exists():
            return {}
        parsed = parse_fichero(abs_path)
        return {
            "fichero_activo_ruta": ruta_activa,
            "fichero_activo_titulo": parsed["title"],
            "fichero_activo_metadata": parsed["metadata"],
            "fichero_activo_content": parsed["content"],
        }
    except Exception:
        return {}


def serializar_capa_como_texto(titulo: str, data: dict) -> str:
    """Aplana un dict de capa a un bloque de texto para la conversación."""
    if not data:
        return ""
    partes = [f"## {titulo}"]
    for k, v in data.items():
        if v is None or v == "":
            continue
        partes.append(f"\n### {k}\n{v if isinstance(v, str) else repr(v)}")
    return "\n".join(partes)
