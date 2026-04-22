"""Usuario único almacenado en users.json."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from ..config import Config


class Usuario(UserMixin):
    def __init__(self, username: str):
        self.id = username
        self.username = username


def _leer_json(ruta: Path) -> dict | None:
    if not ruta.exists():
        return None
    with ruta.open("r", encoding="utf-8") as f:
        return json.load(f)


def _escribir_json(ruta: Path, data: dict) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(ruta.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, ruta)
    try:
        os.chmod(ruta, 0o600)
    except OSError:
        pass


def cargar_usuario_por_id(user_id: str) -> Usuario | None:
    data = _leer_json(Config.USERS_FILE)
    if not data or data.get("username") != user_id:
        return None
    return Usuario(username=data["username"])


def verificar_credenciales(username: str, password: str) -> Usuario | None:
    data = _leer_json(Config.USERS_FILE)
    if not data:
        return None
    if data.get("username") != username:
        return None
    if not check_password_hash(data.get("password_hash", ""), password):
        return None
    return Usuario(username=username)


def actualizar_ultimo_login(username: str) -> None:
    data = _leer_json(Config.USERS_FILE)
    if not data or data.get("username") != username:
        return
    data["last_login"] = datetime.now(timezone.utc).isoformat()
    _escribir_json(Config.USERS_FILE, data)


def establecer_password(username: str, password: str) -> None:
    """Crea o sobrescribe users.json con un hash nuevo."""
    previo = _leer_json(Config.USERS_FILE) or {}
    data = {
        "username": username,
        "password_hash": generate_password_hash(password),
        "created_at": previo.get("created_at") or datetime.now(timezone.utc).isoformat(),
        "last_login": previo.get("last_login"),
    }
    _escribir_json(Config.USERS_FILE, data)
