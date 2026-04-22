"""CLI de gestión.

Uso:
    python manage.py set_password
    python manage.py init_db
    python manage.py new_project <slug> [nombre]
"""
from __future__ import annotations

import getpass
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.config import Config, ensure_dirs


def _set_password(_args: list[str]) -> int:
    from app.auth.models import establecer_password

    ensure_dirs(Config)
    username = input("Usuario: ").strip()
    if not username:
        print("Usuario vacío. Abortado.")
        return 1
    pw1 = getpass.getpass("Contraseña: ")
    pw2 = getpass.getpass("Repite contraseña: ")
    if pw1 != pw2:
        print("Las contraseñas no coinciden. Abortado.")
        return 1
    if len(pw1) < 8:
        print("Mínimo 8 caracteres. Abortado.")
        return 1
    establecer_password(username, pw1)
    print(f"Contraseña establecida para '{username}'. Guardado en {Config.USERS_FILE}")
    return 0


def _init_db(_args: list[str]) -> int:
    from app.audit.db import inicializar_db

    ensure_dirs(Config)
    inicializar_db()
    print(f"Base de datos inicializada en {Config.AUDIT_DB}")
    return 0


def _new_project(args: list[str]) -> int:
    from app.files.project import crear_proyecto_independiente

    ensure_dirs(Config)
    if not args:
        print("Falta el slug del proyecto.")
        return 1
    slug = args[0]
    nombre = args[1] if len(args) > 1 else slug
    ruta = crear_proyecto_independiente(slug=slug, nombre=nombre)
    print(f"Proyecto creado en {ruta}")
    return 0


def _new_saga(args: list[str]) -> int:
    from app.files.project import crear_saga

    ensure_dirs(Config)
    if not args:
        print("Uso: python manage.py new_saga <slug> [nombre]")
        return 1
    slug = args[0]
    nombre = args[1] if len(args) > 1 else slug
    ruta = crear_saga(slug=slug, nombre=nombre)
    print(f"Saga creada en {ruta}")
    return 0


def _add_book(args: list[str]) -> int:
    from app.files.project import añadir_libro_a_saga

    ensure_dirs(Config)
    if len(args) < 3:
        print("Uso: python manage.py add_book <saga_slug> <libro_slug> <nombre> [orden]")
        return 1
    saga_slug, libro_slug, nombre = args[0], args[1], args[2]
    orden = int(args[3]) if len(args) > 3 else 1
    ruta = añadir_libro_a_saga(saga_slug, libro_slug, nombre, orden)
    print(f"Libro creado en {ruta}")
    return 0


COMANDOS = {
    "set_password": _set_password,
    "init_db": _init_db,
    "new_project": _new_project,
    "new_saga": _new_saga,
    "add_book": _add_book,
}


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in COMANDOS:
        print(__doc__)
        print("Comandos disponibles:", ", ".join(sorted(COMANDOS)))
        return 1
    return COMANDOS[argv[1]](argv[2:])


if __name__ == "__main__":
    sys.exit(main(sys.argv))
