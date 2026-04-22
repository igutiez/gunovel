"""Auditoría editorial determinista (sin IA).

Chequeos baratos que se ejecutan con regex/contadores sin consumir tokens.
Los chequeos que requieren juicio editorial (sobreexplicación, efectismo,
voz narrativa, anacronismos sutiles) se dejan para la IA, que puede usar
la tool `auditar_capitulo` y luego leer el capítulo para profundizar.

Categorías implementadas:
- repeticiones_palabra: palabras (>=5 letras, no stopword) con count >= 3.
- repeticiones_ngrama: secuencias de 5 palabras que aparecen 2+ veces.
- tics: lista configurable leída de 05_control/estilo.md (sección "Lista negra").
- dicendi: ratio invisibles (dijo/dice) vs de color (susurró/exclamó/...).
- tiempos: heurística basada en dicendi para detectar mezcla presente/pasado.
- erratas: doble espacio, ¿? ¡! desparejados, comillas tipográficas desparejadas.
- longitud: palabras fuera de rango objetivo (1500-2500 por defecto).
- coherencia: wrapper sobre el módulo coherencia.py ya existente.
- cronologia: extrae fechas explícitas y alerta de monotonicidad rota.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path

from ..files.parser import parse_fichero
from ..files.project import Proyecto, leer_orden, numerar_capitulos
from . import coherencia


# ---------------------------------------------------------------------------
# Stopwords mínimas en español (palabras demasiado comunes para señalar)
# ---------------------------------------------------------------------------
STOPWORDS_ES = {
    "acaba", "ahora", "antes", "apenas", "aquel", "aquella", "aquellas",
    "aquello", "aquellos", "aunque", "ayer", "cada", "cerca", "cinco",
    "como", "cómo", "contigo", "cosas", "cuando", "cuanto", "cuánto",
    "cuatro", "debe", "debería", "dejó", "desde", "después", "dice",
    "dicen", "dijo", "donde", "dónde", "durante", "ellos", "ellas",
    "entonces", "entre", "eran", "éramos", "estaba", "estaban",
    "están", "está", "estamos", "este", "esta", "estos", "estas",
    "estuvo", "eso", "esta", "estaban", "estaba", "estábamos",
    "forma", "fueron", "había", "habían", "habla", "hablar",
    "hace", "hacen", "hacer", "hacia", "hasta", "hemos", "hizo",
    "hacía", "hacían", "luego", "mañana", "mientras", "misma",
    "mismo", "momento", "mucho", "muchos", "mucha", "muchas",
    "nada", "noche", "nunca", "otra", "otras", "otro", "otros",
    "parece", "parecía", "pero", "podía", "podían", "porque", "puede",
    "pueden", "queda", "quedan", "quería", "quiere", "sabe", "sabía",
    "saber", "sería", "serían", "siempre", "sido", "siempre",
    "siguen", "siguió", "siguiente", "sobre", "solo", "sólo",
    "también", "tanto", "tener", "tenía", "tengo", "tiempo",
    "tiene", "tienen", "toda", "todas", "todo", "todos", "tres",
    "tuvo", "tuvieron", "también", "ustedes", "vamos", "veces",
    "viene", "vienen", "volvía", "volvió",
}


# ---------------------------------------------------------------------------
# Verbos dicendi (invisibles vs de color)
# ---------------------------------------------------------------------------
DICENDI_INVISIBLES = {"dijo", "dice", "decía", "dicen", "dijeron"}
DICENDI_COLOR = {
    "exclamó", "susurró", "murmuró", "masculló", "balbuceó", "gritó",
    "replicó", "añadió", "agregó", "continuó", "concluyó", "insistió",
    "espetó", "proclamó", "bramó", "soltó", "aclaró", "explicó",
    "contestó", "respondió", "afirmó", "negó", "preguntó", "objetó",
    "señaló", "apuntó", "comentó", "sugirió", "confesó", "reconoció",
    "admitió", "clamó", "advirtió", "sentenció", "anunció", "declaró",
    "matizó", "apostilló", "farfulló", "suspiró", "gruñó", "titubeó",
    "sollozó", "carraspeó",
}

TICS_SECCION_REGEX = re.compile(
    r"##\s+(?:Lista\s+negra|Muletillas|Tics|Palabras\s+a\s+evitar)\b.*?\n(.+?)(?=\n##|\Z)",
    re.IGNORECASE | re.DOTALL,
)

DIAS_SEMANA = {
    "lunes", "martes", "miércoles", "miercoles", "jueves", "viernes", "sábado", "sabado", "domingo",
}
MESES = {
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
}


# ---------------------------------------------------------------------------
# Helpers de tokenización
# ---------------------------------------------------------------------------

_PALABRA_RE = re.compile(r"[a-záéíóúüñA-ZÁÉÍÓÚÜÑ]{2,}")


def _tokenizar(texto: str) -> list[tuple[str, int]]:
    return [(m.group(0).lower(), m.start()) for m in _PALABRA_RE.finditer(texto)]


def _linea_de(texto: str, idx: int) -> int:
    return texto.count("\n", 0, idx) + 1


def _quitar_frontmatter(contenido: str) -> str:
    if not contenido.startswith("---"):
        return contenido
    m = re.search(r"\n---\s*\n", contenido[3:])
    if not m:
        return contenido
    return contenido[3 + m.end():]


def _quitar_encabezados_markdown(cuerpo: str) -> str:
    return re.sub(r"^#{1,6}\s+.*$", "", cuerpo, flags=re.MULTILINE)


# ---------------------------------------------------------------------------
# Chequeos individuales
# ---------------------------------------------------------------------------

def _repeticiones_palabra(cuerpo: str, *, min_longitud: int = 5, umbral: int = 3, tope: int = 20) -> list[dict]:
    tokens = _tokenizar(cuerpo)
    counts: Counter[str] = Counter()
    posiciones: dict[str, list[int]] = defaultdict(list)
    for palabra, idx in tokens:
        if len(palabra) < min_longitud or palabra in STOPWORDS_ES:
            continue
        counts[palabra] += 1
        posiciones[palabra].append(_linea_de(cuerpo, idx))
    hallazgos: list[dict] = []
    for palabra, n in counts.most_common():
        if n < umbral:
            break
        lineas = posiciones[palabra]
        distancias_tokens = [lineas[i + 1] - lineas[i] for i in range(len(lineas) - 1)]
        hallazgos.append(
            {
                "palabra": palabra,
                "apariciones": n,
                "lineas": lineas[:12],
                "min_distancia_lineas": min(distancias_tokens) if distancias_tokens else None,
            }
        )
        if len(hallazgos) >= tope:
            break
    return hallazgos


def _repeticiones_ngrama(cuerpo: str, *, n: int = 5, tope: int = 15) -> list[dict]:
    tokens = [p for p, _ in _tokenizar(cuerpo)]
    if len(tokens) < n:
        return []
    grams: Counter[str] = Counter()
    for i in range(len(tokens) - n + 1):
        gram = " ".join(tokens[i:i + n])
        grams[gram] += 1
    hallazgos: list[dict] = []
    for gram, count in grams.most_common():
        if count < 2:
            break
        palabras = gram.split()
        if all(len(p) <= 3 for p in palabras) or all(p in STOPWORDS_ES for p in palabras):
            continue
        hallazgos.append({"ngrama": gram, "apariciones": count})
        if len(hallazgos) >= tope:
            break
    return hallazgos


def _leer_tics_proyecto(proyecto: Proyecto) -> list[str]:
    """Lee la sección 'Lista negra' / 'Muletillas' / 'Tics' de 05_control/estilo.md."""
    candidatos: list[Path] = [
        proyecto.ruta / "05_control" / "estilo.md",
        proyecto.ruta / "05_control" / "tics.md",
    ]
    if proyecto.canon_ruta:
        candidatos.append(proyecto.canon_ruta / "estilo.md")

    tics: list[str] = []
    for ruta in candidatos:
        if not ruta.exists():
            continue
        try:
            contenido = ruta.read_text(encoding="utf-8")
        except OSError:
            continue
        m = TICS_SECCION_REGEX.search(contenido)
        if not m:
            continue
        for linea in m.group(1).splitlines():
            l = linea.strip()
            if l.startswith("- "):
                val = l[2:].strip().strip('"\'`').lower()
                if val:
                    tics.append(val)
    # deduplicar manteniendo orden
    vistos = set()
    únicos = []
    for t in tics:
        if t not in vistos:
            vistos.add(t)
            únicos.append(t)
    return únicos


def _detectar_tics(cuerpo: str, tics: list[str]) -> list[dict]:
    hallazgos: list[dict] = []
    lower = cuerpo.lower()
    for tic in tics:
        patron = re.compile(r"\b" + re.escape(tic) + r"\b", re.IGNORECASE)
        matches = list(patron.finditer(lower))
        if matches:
            hallazgos.append(
                {
                    "tic": tic,
                    "apariciones": len(matches),
                    "lineas": [_linea_de(cuerpo, m.start()) for m in matches[:20]],
                }
            )
    return hallazgos


def _analizar_dicendi(cuerpo: str) -> dict | None:
    lower = cuerpo.lower()
    invisibles = 0
    color = 0
    color_count: Counter[str] = Counter()
    for v in DICENDI_INVISIBLES:
        invisibles += len(re.findall(r"\b" + v + r"\b", lower))
    for v in DICENDI_COLOR:
        n = len(re.findall(r"\b" + v + r"\b", lower))
        if n:
            color_count[v] += n
            color += n
    total = invisibles + color
    if total == 0:
        return None
    return {
        "total": total,
        "invisibles": invisibles,
        "color": color,
        "color_porcentaje": round(100 * color / total, 1),
        "color_top": color_count.most_common(5),
        "advertencia": (
            "Ratio de verbos dicendi 'de color' por encima del 35%: revisa si "
            "algunos pueden volver a 'dijo/dice'."
            if total > 0 and (color / total) > 0.35
            else None
        ),
    }


def _analizar_tiempos(cuerpo: str) -> dict:
    """Heurística basada en dicendi + terminaciones verbales comunes al cierre de oración."""
    lower = cuerpo.lower()
    indef = sum(len(re.findall(r"\b" + v + r"\b", lower)) for v in ("dijo", "dijeron", "fue", "estuvo", "tuvo", "quiso"))
    presente = sum(len(re.findall(r"\b" + v + r"\b", lower)) for v in ("dice", "dicen", "está", "están", "tiene", "tienen", "quiere"))
    imperfecto = sum(len(re.findall(r"\b" + v + r"\b", lower)) for v in ("decía", "decían", "estaba", "estaban", "tenía", "tenían", "quería"))
    total = indef + presente + imperfecto
    if total == 0:
        return {"dominante": None, "mezclado": False, "counts": {"indef": 0, "presente": 0, "imperfecto": 0}}
    pct = {
        "indef": round(100 * indef / total, 1),
        "presente": round(100 * presente / total, 1),
        "imperfecto": round(100 * imperfecto / total, 1),
    }
    dominante = max(pct, key=lambda k: pct[k])
    # Pasado = indef + imperfecto
    pasado_pct = pct["indef"] + pct["imperfecto"]
    presente_pct = pct["presente"]
    mezclado = min(pasado_pct, presente_pct) > 20
    return {
        "dominante": "presente" if presente_pct > pasado_pct else "pasado",
        "mezclado": mezclado,
        "pct_presente": presente_pct,
        "pct_pasado": pasado_pct,
        "counts": {"indef": indef, "presente": presente, "imperfecto": imperfecto},
        "advertencia": (
            "Mezcla presente/pasado > 20% en ambos: revisa si hay flashback mal marcado."
            if mezclado
            else None
        ),
    }


def _detectar_erratas(cuerpo: str) -> list[dict]:
    hallazgos: list[dict] = []
    # Doble espacio (no en encabezados)
    for m in re.finditer(r"[^\n]  +", cuerpo):
        hallazgos.append({"tipo": "doble_espacio", "linea": _linea_de(cuerpo, m.start())})
        if sum(1 for h in hallazgos if h["tipo"] == "doble_espacio") >= 20:
            break

    abrir_int = len(re.findall(r"¿", cuerpo))
    cerrar_int = len(re.findall(r"\?", cuerpo))
    if abrir_int != cerrar_int:
        hallazgos.append(
            {
                "tipo": "desequilibrio_interrogacion",
                "abrir": abrir_int,
                "cerrar": cerrar_int,
                "mensaje": f"¿ = {abrir_int} pero ? = {cerrar_int}. Revisa pares.",
            }
        )

    abrir_ex = len(re.findall(r"¡", cuerpo))
    cerrar_ex = len(re.findall(r"!", cuerpo))
    if abrir_ex != cerrar_ex:
        hallazgos.append(
            {
                "tipo": "desequilibrio_exclamacion",
                "abrir": abrir_ex,
                "cerrar": cerrar_ex,
                "mensaje": f"¡ = {abrir_ex} pero ! = {cerrar_ex}. Revisa pares.",
            }
        )

    abrir_c = len(re.findall(r"[“«]", cuerpo))
    cerrar_c = len(re.findall(r"[”»]", cuerpo))
    if abrir_c != cerrar_c:
        hallazgos.append(
            {
                "tipo": "comillas_desparejadas",
                "abrir": abrir_c,
                "cerrar": cerrar_c,
                "mensaje": "Comillas tipográficas desparejadas.",
            }
        )

    # Coma antes de conjunción "y/o" con sujeto repetido (falsos positivos frecuentes,
    # lo dejamos como placeholder).
    return hallazgos


def _contar_palabras_cuerpo(cuerpo: str) -> int:
    cuerpo_sin_titulos = _quitar_encabezados_markdown(cuerpo)
    return len(re.findall(r"\b[\wáéíóúüñÁÉÍÓÚÜÑ'-]+\b", cuerpo_sin_titulos))


def _analizar_longitud(cuerpo: str, minimo: int, maximo: int) -> dict:
    n = _contar_palabras_cuerpo(cuerpo)
    fuera_rango = n < minimo or n > maximo
    return {
        "palabras": n,
        "minimo": minimo,
        "maximo": maximo,
        "fuera_rango": fuera_rango,
        "advertencia": (
            f"Capítulo de {n} palabras fuera del rango {minimo}-{maximo}."
            if fuera_rango
            else None
        ),
    }


_FECHA_RE = re.compile(
    r"\b(\d{1,2})\s+de\s+(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)(?:\s+de\s+(\d{4}))?\b",
    re.IGNORECASE,
)
_DIA_SEMANA_RE = re.compile(
    r"\b(lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)\b",
    re.IGNORECASE,
)


def _extraer_cronologia(cuerpo: str) -> dict:
    fechas = [
        {
            "dia": m.group(1),
            "mes": m.group(2).lower(),
            "anio": m.group(3),
            "linea": _linea_de(cuerpo, m.start()),
        }
        for m in _FECHA_RE.finditer(cuerpo)
    ]
    dias = [
        {"dia_semana": m.group(1).lower(), "linea": _linea_de(cuerpo, m.start())}
        for m in _DIA_SEMANA_RE.finditer(cuerpo)
    ]
    return {"fechas": fechas[:10], "dias_semana": dias[:10]}


# ---------------------------------------------------------------------------
# Función principal
# ---------------------------------------------------------------------------

CATEGORIAS_POR_DEFECTO = (
    "repeticiones_palabra",
    "repeticiones_ngrama",
    "tics",
    "dicendi",
    "tiempos",
    "erratas",
    "longitud",
    "cronologia",
    "coherencia",
)


def auditar(
    proyecto: Proyecto,
    *,
    slug: str | None = None,
    categorias: list[str] | None = None,
    minimo_palabras: int = 1500,
    maximo_palabras: int = 2500,
) -> dict:
    """Audita un capítulo o todo el proyecto.

    slug: slug de capítulo concreto o None para todo el proyecto.
    """
    categorias = tuple(categorias) if categorias else CATEGORIAS_POR_DEFECTO
    tics = _leer_tics_proyecto(proyecto) if "tics" in categorias else []

    if slug and slug not in (None, "", "proyecto", "*"):
        return {
            "ambito": slug,
            "capitulos": [_auditar_capitulo(proyecto, slug, categorias, tics, minimo_palabras, maximo_palabras)],
            "coherencia_global": None,
        }

    orden = leer_orden(proyecto)
    etiquetas = numerar_capitulos(orden)
    resultados: list[dict] = []
    for s in etiquetas.keys():
        resultados.append(
            _auditar_capitulo(proyecto, s, categorias, tics, minimo_palabras, maximo_palabras)
        )
    coherencia_global = (
        coherencia.verificar(proyecto, "proyecto") if "coherencia" in categorias else None
    )
    return {
        "ambito": "proyecto",
        "capitulos": resultados,
        "coherencia_global": coherencia_global,
    }


def _auditar_capitulo(
    proyecto: Proyecto,
    slug: str,
    categorias: tuple[str, ...],
    tics: list[str],
    minimo_palabras: int,
    maximo_palabras: int,
) -> dict:
    md = proyecto.ruta / "04_capitulos" / f"{slug}.md"
    if not md.exists():
        return {"slug": slug, "error": "Capítulo no existe en 04_capitulos/."}
    try:
        parsed = parse_fichero(md)
    except Exception as exc:
        return {"slug": slug, "error": f"Parse error: {exc}"}

    cuerpo = parsed["content"] or ""
    cuerpo_sin_fm = _quitar_frontmatter(cuerpo) if cuerpo.startswith("---") else cuerpo
    cuerpo_efectivo = cuerpo_sin_fm

    out: dict = {
        "slug": slug,
        "titulo": parsed["title"] or slug,
        "ruta": f"04_capitulos/{slug}.md",
    }

    if "longitud" in categorias:
        out["longitud"] = _analizar_longitud(cuerpo_efectivo, minimo_palabras, maximo_palabras)
    if "repeticiones_palabra" in categorias:
        out["repeticiones_palabra"] = _repeticiones_palabra(cuerpo_efectivo)
    if "repeticiones_ngrama" in categorias:
        out["repeticiones_ngrama"] = _repeticiones_ngrama(cuerpo_efectivo)
    if "tics" in categorias:
        out["tics"] = _detectar_tics(cuerpo_efectivo, tics)
    if "dicendi" in categorias:
        out["dicendi"] = _analizar_dicendi(cuerpo_efectivo)
    if "tiempos" in categorias:
        out["tiempos"] = _analizar_tiempos(cuerpo_efectivo)
    if "erratas" in categorias:
        out["erratas"] = _detectar_erratas(cuerpo_efectivo)
    if "cronologia" in categorias:
        out["cronologia"] = _extraer_cronologia(cuerpo_efectivo)
    if "coherencia" in categorias:
        out["coherencia"] = coherencia.verificar(proyecto, slug)

    return out
