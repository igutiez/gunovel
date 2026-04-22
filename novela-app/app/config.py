"""Carga de configuración desde entorno."""
from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv


_BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(_BASE_DIR / ".env")


def _get(name: str, default: str | None = None, required: bool = False) -> str:
    value = os.environ.get(name, default)
    if required and not value:
        raise RuntimeError(f"Variable de entorno obligatoria no definida: {name}")
    return value or ""


class Config:
    SECRET_KEY = _get("SECRET_KEY", required=True)

    NOVELAS_ROOT = Path(_get("NOVELAS_ROOT", str(Path.home() / "novelas")))
    APP_CONFIG_DIR = Path(_get("APP_CONFIG_DIR", str(Path.home() / "novela-app-config")))

    ANTHROPIC_API_KEY = _get("ANTHROPIC_API_KEY")

    SESSION_LIFETIME_HOURS = int(_get("SESSION_LIFETIME_HOURS", "8"))
    PERMANENT_SESSION_LIFETIME = timedelta(hours=SESSION_LIFETIME_HOURS)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Strict"
    SESSION_COOKIE_SECURE = _get("FLASK_ENV", "development") != "development"

    USD_TO_EUR = float(_get("USD_TO_EUR", "0.92"))

    LOG_LEVEL = _get("LOG_LEVEL", "INFO")
    LOG_DIR = Path(_get("LOG_DIR", str(APP_CONFIG_DIR / "logs")))

    DEBUG = _get("FLASK_DEBUG", "0") == "1"

    USERS_FILE = APP_CONFIG_DIR / "users.json"
    AUDIT_DB = APP_CONFIG_DIR / "audit.db"

    MODELO_POR_DEFECTO = "claude-sonnet-4-6"
    MODELO_OPUS = "claude-opus-4-7"
    MODELO_HAIKU = "claude-haiku-4-5"
    MAX_TOOL_CALLS_POR_TURNO = 5
    MAX_CHARS_TOOL_RESULT = 8000
    VENTANA_HISTORIAL_MENSAJES = 50
    UMBRAL_RESUMIR_HISTORIAL = 40


def ensure_dirs(cfg: type[Config]) -> None:
    """Crea los directorios base si no existen."""
    cfg.NOVELAS_ROOT.mkdir(parents=True, exist_ok=True)
    cfg.APP_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    cfg.LOG_DIR.mkdir(parents=True, exist_ok=True)
    (cfg.NOVELAS_ROOT / "independientes").mkdir(exist_ok=True)
    (cfg.NOVELAS_ROOT / "sagas").mkdir(exist_ok=True)
