"""Access log rotado semanalmente."""
from __future__ import annotations

import logging
from logging.handlers import TimedRotatingFileHandler

from ..config import Config


_logger: logging.Logger | None = None


def _get_logger() -> logging.Logger:
    global _logger
    if _logger is not None:
        return _logger
    Config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("novela_app.access")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = TimedRotatingFileHandler(
        Config.LOG_DIR / "access.log", when="W0", backupCount=4, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", "%Y-%m-%d %H:%M:%S"))
    logger.addHandler(handler)
    _logger = logger
    return logger


def log_acceso(tipo: str, usuario: str, ip: str) -> None:
    _get_logger().info("%s %s desde %s", tipo, usuario, ip)
