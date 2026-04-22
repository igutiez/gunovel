"""Parsing y escritura de ficheros Markdown con frontmatter YAML."""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

import frontmatter


SLUG_RE = re.compile(r"^[a-z0-9_]+$")


class SlugInvalidoError(ValueError):
    pass


class RutaNoPermitidaError(ValueError):
    pass


def validar_slug(slug: str) -> None:
    if not slug or not SLUG_RE.match(slug):
        raise SlugInvalidoError(
            f"Slug inválido '{slug}': solo ASCII minúsculas, dígitos y '_'."
        )


def extraer_titulo(contenido: str) -> str | None:
    """Devuelve el texto del primer encabezado '# ...' o None."""
    for linea in contenido.splitlines():
        stripped = linea.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return None


def parse_fichero(ruta: Path) -> dict:
    """Lee un fichero .md y devuelve {metadata, content, title}."""
    with ruta.open("r", encoding="utf-8") as f:
        post = frontmatter.load(f)
    contenido = post.content
    return {
        "metadata": dict(post.metadata),
        "content": contenido,
        "title": extraer_titulo(contenido),
    }


def escribir_fichero(ruta: Path, metadata: dict | None, content: str) -> None:
    """Escribe un fichero atómicamente: a .tmp y luego renombra."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    if metadata:
        post = frontmatter.Post(content, **metadata)
        contenido_serializado = frontmatter.dumps(post, sort_keys=False)
    else:
        contenido_serializado = content
    if not contenido_serializado.endswith("\n"):
        contenido_serializado += "\n"
    fd, tmp_path = tempfile.mkstemp(
        dir=str(ruta.parent), prefix=f".{ruta.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(contenido_serializado)
        os.replace(tmp_path, ruta)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def escribir_raw(ruta: Path, contenido: str) -> None:
    """Escritura atómica sin tocar frontmatter (útil para orden.json)."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(ruta.parent), prefix=f".{ruta.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(contenido)
        os.replace(tmp_path, ruta)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def validar_frontmatter(ruta_rel: str, contenido: str) -> list[str]:
    """Valida la cabecera YAML contra reglas mínimas por tipo de fichero.

    Devuelve lista de avisos (strings). Lista vacía = todo OK.
    No bloquea la escritura: la capa de ficheros decide qué hacer con avisos.
    """
    avisos: list[str] = []
    try:
        post = frontmatter.loads(contenido)
    except Exception as exc:  # noqa: BLE001
        return [f"Frontmatter inválido: {exc}"]

    meta = post.metadata or {}
    slug_fichero = Path(ruta_rel).stem

    if meta.get("slug") and meta["slug"] != slug_fichero:
        avisos.append(
            f"slug en cabecera ('{meta['slug']}') no coincide con nombre de fichero ('{slug_fichero}')."
        )

    if ruta_rel.startswith("04_capitulos/"):
        for campo in ("slug",):
            if campo not in meta:
                avisos.append(f"Capítulo sin '{campo}' en cabecera.")
        estado = meta.get("estado")
        estados_validos = {"esqueleto", "borrador", "borrador_v2", "revisado", "cerrado"}
        if estado and estado not in estados_validos:
            avisos.append(f"estado '{estado}' no es uno de {sorted(estados_validos)}.")
        personajes = meta.get("personajes")
        if personajes is not None and not isinstance(personajes, list):
            avisos.append("'personajes' debe ser una lista de slugs.")

    if ruta_rel.startswith("01_personajes/"):
        if meta.get("tipo") not in (None, "personaje"):
            avisos.append("En 01_personajes/ tipo debería ser 'personaje'.")
        rol = meta.get("rol")
        roles_validos = {"principal", "secundario", "terciario", "mencionado"}
        if rol and rol not in roles_validos:
            avisos.append(f"rol '{rol}' no es uno de {sorted(roles_validos)}.")

    if ruta_rel.startswith("02_mundo/") and slug_fichero not in ("worldbuilding", "glosario", "mapa"):
        if meta.get("tipo") not in (None, "lugar"):
            avisos.append("En 02_mundo/ tipo debería ser 'lugar'.")

    return avisos


def ruta_segura(base: Path, ruta_relativa: str) -> Path:
    """Resuelve una ruta relativa y verifica que sigue dentro de `base`.

    Rechaza rutas absolutas y cualquier intento de salirse con '..'.
    """
    if not ruta_relativa:
        raise RutaNoPermitidaError("Ruta vacía.")
    candidato = Path(ruta_relativa)
    if candidato.is_absolute():
        raise RutaNoPermitidaError(f"No se permiten rutas absolutas: {ruta_relativa}")
    resuelta = (base / candidato).resolve()
    base_resuelta = base.resolve()
    try:
        resuelta.relative_to(base_resuelta)
    except ValueError as exc:
        raise RutaNoPermitidaError(
            f"La ruta {ruta_relativa} sale del proyecto."
        ) from exc
    return resuelta
