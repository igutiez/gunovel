"""Edición estructural del fichero 03_estructura/relaciones.md.

Convención: secciones jerárquicas estilo

    # Grafo de relaciones
    ## Por capítulo
    ### <slug_cap>
    - linea
    - linea

    ## Por personaje
    ### <slug_pers>
    - linea

Los cambios propuestos por la IA son:
    {"accion": "añadir" | "modificar" | "eliminar", "seccion": "Por capítulo/jose_luis", "texto": "..."}

- `añadir`: añade las líneas de `texto` (pueden ser varias separadas por \\n) al final de esa sección.
- `modificar`: reemplaza el cuerpo completo de esa sección por `texto`.
- `eliminar`: borra la sección.

Si la sección no existe, se crea en el lugar correcto.
"""
from __future__ import annotations

import re


ROOT_TITULO = "# Grafo de relaciones"


def aplicar_cambios_grafo(contenido_actual: str, cambios: list[dict]) -> str:
    if not contenido_actual.strip():
        contenido_actual = ROOT_TITULO + "\n"
    if not contenido_actual.lstrip().startswith("# "):
        contenido_actual = ROOT_TITULO + "\n\n" + contenido_actual

    for c in cambios:
        accion = (c.get("accion") or "").lower().strip()
        ruta = (c.get("seccion") or "").strip()
        texto = c.get("texto") or ""
        if not ruta:
            continue
        partes = [p.strip() for p in ruta.split("/") if p.strip()]
        if not partes:
            continue
        if accion in ("añadir", "anadir", "add", "append"):
            contenido_actual = _añadir(contenido_actual, partes, texto)
        elif accion in ("modificar", "reemplazar", "replace"):
            contenido_actual = _modificar(contenido_actual, partes, texto)
        elif accion in ("eliminar", "borrar", "delete"):
            contenido_actual = _eliminar(contenido_actual, partes)
        else:
            # Desconocida → tratar como añadir seguro.
            contenido_actual = _añadir(contenido_actual, partes, texto)
    return contenido_actual if contenido_actual.endswith("\n") else contenido_actual + "\n"


# Un "segmento" es (nivel, titulo, cuerpo, linea_inicio, linea_fin)

def _parsear(contenido: str) -> list[tuple[int, str, list[str]]]:
    """Devuelve una lista de bloques [(nivel_hashes, titulo, lineas_cuerpo)]."""
    bloques: list[tuple[int, str, list[str]]] = []
    actual: tuple[int, str, list[str]] | None = None
    for linea in contenido.splitlines():
        m = re.match(r"^(#{1,6})\s+(.*)$", linea)
        if m:
            if actual is not None:
                bloques.append(actual)
            actual = (len(m.group(1)), m.group(2).strip(), [])
        else:
            if actual is None:
                # Texto antes del primer heading: lo descartamos (se normaliza).
                continue
            actual[2].append(linea)
    if actual is not None:
        bloques.append(actual)
    return bloques


def _serializar(bloques: list[tuple[int, str, list[str]]]) -> str:
    out: list[str] = []
    for nivel, titulo, cuerpo in bloques:
        out.append("#" * nivel + " " + titulo)
        # Recortar líneas en blanco al final del cuerpo.
        while cuerpo and cuerpo[-1].strip() == "":
            cuerpo.pop()
        out.extend(cuerpo)
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def _buscar_indice(
    bloques: list[tuple[int, str, list[str]]], ruta: list[str]
) -> int:
    """Índice del bloque que matchea la ruta jerárquica, o -1."""
    nivel_esperado = 2  # "## " para el primer segmento (debajo del H1 raíz).
    i = 0
    for seg in ruta:
        encontrado = False
        while i < len(bloques):
            nivel, titulo, _ = bloques[i]
            if nivel < nivel_esperado:
                return -1
            if nivel == nivel_esperado and _coincide(titulo, seg):
                encontrado = True
                break
            i += 1
        if not encontrado:
            return -1
        nivel_esperado += 1
        i += 1  # Buscamos los hijos después del bloque encontrado.
    return i - 1


def _coincide(a: str, b: str) -> bool:
    return a.strip().lower() == b.strip().lower()


def _indice_fin_subarbol(bloques: list, idx_inicio: int) -> int:
    """Primer índice > idx_inicio cuyo nivel <= nivel del bloque idx_inicio."""
    nivel = bloques[idx_inicio][0]
    for i in range(idx_inicio + 1, len(bloques)):
        if bloques[i][0] <= nivel:
            return i
    return len(bloques)


def _añadir(contenido: str, ruta: list[str], texto: str) -> str:
    bloques = _parsear(contenido)
    idx = _buscar_indice(bloques, ruta)
    lineas_texto = texto.splitlines() if texto else []
    if idx >= 0:
        nivel, titulo, cuerpo = bloques[idx]
        cuerpo = list(cuerpo) + lineas_texto
        bloques[idx] = (nivel, titulo, cuerpo)
    else:
        # Crear la sección en la posición correcta.
        bloques = _insertar_seccion(bloques, ruta, lineas_texto)
    return _serializar(bloques)


def _modificar(contenido: str, ruta: list[str], texto: str) -> str:
    bloques = _parsear(contenido)
    idx = _buscar_indice(bloques, ruta)
    lineas_texto = texto.splitlines() if texto else []
    if idx >= 0:
        nivel, titulo, _ = bloques[idx]
        bloques[idx] = (nivel, titulo, lineas_texto)
    else:
        bloques = _insertar_seccion(bloques, ruta, lineas_texto)
    return _serializar(bloques)


def _eliminar(contenido: str, ruta: list[str]) -> str:
    bloques = _parsear(contenido)
    idx = _buscar_indice(bloques, ruta)
    if idx < 0:
        return contenido
    fin = _indice_fin_subarbol(bloques, idx)
    del bloques[idx:fin]
    return _serializar(bloques)


def _insertar_seccion(
    bloques: list, ruta: list[str], lineas_texto: list[str]
) -> list:
    """Inserta una sección nueva, creando padres intermedios si faltan."""
    prefijo_actual: list[str] = []
    for idx_seg, seg in enumerate(ruta):
        prefijo_actual.append(seg)
        idx = _buscar_indice(bloques, prefijo_actual)
        if idx >= 0:
            continue
        # Hay que crear esta sección; si estamos en el último segmento, le ponemos cuerpo.
        nivel = 2 + idx_seg
        cuerpo = lineas_texto if idx_seg == len(ruta) - 1 else []
        # Insertar al final del subárbol padre (o al final del fichero si no hay padre).
        if idx_seg == 0:
            # Sección de nivel 2 → después de la última sección de nivel >=2 existente.
            pos = len(bloques)
        else:
            padre = prefijo_actual[:-1]
            idx_padre = _buscar_indice(bloques, padre)
            if idx_padre < 0:
                pos = len(bloques)
            else:
                pos = _indice_fin_subarbol(bloques, idx_padre)
        bloques.insert(pos, (nivel, seg, list(cuerpo)))
    return bloques
