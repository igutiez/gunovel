"""Backup consistente del audit.db.

Uso manual o desde cron:
    python scripts/backup_audit_db.py [--dir /ruta/backups] [--retain 30]

Usa `sqlite3 .backup` para consistencia (API Python Connection.backup).
Mantiene retención de N días por defecto.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Permitir ejecutar desde la raíz del proyecto.
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from app.config import Config  # noqa: E402


def backup(dir_backup: Path) -> Path:
    dir_backup.mkdir(parents=True, exist_ok=True)
    fecha = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    destino = dir_backup / f"audit_{fecha}.db"
    src = sqlite3.connect(str(Config.AUDIT_DB))
    dst = sqlite3.connect(str(destino))
    try:
        with dst:
            src.backup(dst)
    finally:
        src.close()
        dst.close()
    return destino


def limpiar(dir_backup: Path, retain_days: int) -> int:
    if retain_days <= 0:
        return 0
    corte = time.time() - retain_days * 86400
    n = 0
    for f in dir_backup.glob("audit_*.db"):
        if f.stat().st_mtime < corte:
            f.unlink(missing_ok=True)
            n += 1
    return n


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dir",
        type=Path,
        default=Config.APP_CONFIG_DIR / "backups",
        help="Directorio de destino.",
    )
    parser.add_argument("--retain", type=int, default=30, help="Días de retención.")
    args = parser.parse_args()
    destino = backup(args.dir)
    borrados = limpiar(args.dir, args.retain)
    print(f"Backup creado: {destino}")
    if borrados:
        print(f"Eliminados {borrados} backup(s) antiguos (>{args.retain}d).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
