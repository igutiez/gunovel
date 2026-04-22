"""Exportación de novela a EPUB desde orden.json + capítulos."""
from __future__ import annotations

import io
import logging
from pathlib import Path

import markdown as md_lib
from ebooklib import epub

from ..files.parser import parse_fichero
from ..files.project import Proyecto, leer_orden, numerar_capitulos


log = logging.getLogger("novela_app.export")


def construir_epub(proyecto: Proyecto) -> bytes:
    """Devuelve los bytes de un EPUB con los capítulos del proyecto en orden."""
    orden = leer_orden(proyecto)
    etiquetas = numerar_capitulos(orden)
    slugs_en_orden = list(etiquetas.keys())

    book = epub.EpubBook()
    book.set_identifier(f"novela-{proyecto.slug}")
    book.set_title(proyecto.nombre)
    book.set_language(proyecto.config.get("idioma") or "es")
    book.add_author("Autor")

    capitulos_epub = []
    for slug in slugs_en_orden:
        md = proyecto.ruta / "04_capitulos" / f"{slug}.md"
        if not md.exists():
            log.warning("Capítulo faltante al exportar: %s", slug)
            continue
        parsed = parse_fichero(md)
        titulo = parsed["title"] or slug
        etiqueta = etiquetas.get(slug, titulo)
        contenido_md = parsed["content"]

        # El primer "# Título" de la prosa ya lo usa EasyMDE como título.
        # Para el EPUB construimos la cabecera con la etiqueta numerada.
        html = md_lib.markdown(contenido_md, extensions=["extra"])
        cap_html = (
            f'<h1 class="etiqueta">{_escape(etiqueta)}</h1>'
            f'<h2 class="titulo">{_escape(titulo)}</h2>'
            f"{html}"
        )

        capitulo = epub.EpubHtml(
            title=etiqueta,
            file_name=f"{slug}.xhtml",
            lang=proyecto.config.get("idioma") or "es",
        )
        capitulo.content = cap_html
        book.add_item(capitulo)
        capitulos_epub.append(capitulo)

    # Si no hay capítulos, añadimos un placeholder para que el EPUB sea válido.
    if not capitulos_epub:
        placeholder = epub.EpubHtml(
            title="Sin capítulos",
            file_name="sin_capitulos.xhtml",
            lang=proyecto.config.get("idioma") or "es",
        )
        placeholder.content = (
            "<h1>Sin capítulos</h1>"
            "<p>Este proyecto no tiene capítulos en <code>orden.json</code> aún.</p>"
        )
        book.add_item(placeholder)
        capitulos_epub.append(placeholder)

    # Página de título
    portada = epub.EpubHtml(
        title=proyecto.nombre,
        file_name="portada.xhtml",
        lang=proyecto.config.get("idioma") or "es",
    )
    portada.content = f'<h1 style="text-align:center">{_escape(proyecto.nombre)}</h1>'
    book.add_item(portada)

    # TOC y spine
    book.toc = [epub.Link(c.file_name, c.title, c.file_name.replace(".xhtml", "")) for c in capitulos_epub]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    style = (
        "body { font-family: Georgia, serif; line-height: 1.55; margin: 2em; }"
        "h1.etiqueta { font-size: 0.8em; text-transform: uppercase; color: #555; margin-bottom: 0; }"
        "h2.titulo { margin-top: 0.2em; font-size: 1.6em; }"
        "p { text-align: justify; text-indent: 1.2em; margin: 0 0 0.3em 0; }"
    )
    css = epub.EpubItem(
        uid="style_default",
        file_name="style/default.css",
        media_type="text/css",
        content=style,
    )
    book.add_item(css)
    for c in capitulos_epub:
        c.add_item(css)
    portada.add_item(css)

    book.spine = ["nav", portada, *capitulos_epub]

    buffer = io.BytesIO()
    epub.write_epub(buffer, book, {})
    return buffer.getvalue()


def _escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
