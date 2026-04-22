"""Cálculo de coste por llamada.

Precios por millón de tokens (USD). Ajustables si cambian.
Referencia aproximada Anthropic; el valor exacto lo configura el operador
según su facturación real.
"""
from __future__ import annotations

from ..config import Config


PRECIOS_USD_POR_MTOK = {
    # modelo -> (input, input_cache_read, input_cache_write_5m, output)
    "claude-haiku-4-5": (1.0, 0.10, 1.25, 5.0),
    "claude-sonnet-4-6": (3.0, 0.30, 3.75, 15.0),
    "claude-opus-4-7": (15.0, 1.50, 18.75, 75.0),
}


def calcular_coste_eur(
    modelo: str,
    tokens_input: int,
    tokens_cache_read: int,
    tokens_cache_write: int,
    tokens_output: int,
) -> float:
    precios = PRECIOS_USD_POR_MTOK.get(modelo) or PRECIOS_USD_POR_MTOK["claude-sonnet-4-6"]
    pin, pcr, pcw, pout = precios
    usd = (
        tokens_input * pin
        + tokens_cache_read * pcr
        + tokens_cache_write * pcw
        + tokens_output * pout
    ) / 1_000_000
    return round(usd * Config.USD_TO_EUR, 6)
