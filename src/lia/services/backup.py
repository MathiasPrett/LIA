import datetime as dt
import sqlite3
from pathlib import Path


def backup_database(database_path: Path, backup_dir: Path, now: dt.datetime) -> Path:
    """Copia de seguridad en caliente vía la API `.backup()` de sqlite3 (segura con el proceso escribiendo)."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    dest = backup_dir / f"lia-{now.strftime('%Y%m%d-%H%M%S')}.db"

    source_conn = sqlite3.connect(str(database_path))
    dest_conn = sqlite3.connect(str(dest))
    try:
        source_conn.backup(dest_conn)
    finally:
        dest_conn.close()
        source_conn.close()

    return dest


def prune_old_backups(backup_dir: Path, retention_days: int, now: dt.datetime) -> list[Path]:
    if not backup_dir.exists():
        return []

    cutoff = now - dt.timedelta(days=retention_days)
    removed = []
    for path in backup_dir.glob("lia-*.db"):
        mtime = dt.datetime.fromtimestamp(path.stat().st_mtime)
        if mtime < cutoff:
            path.unlink()
            removed.append(path)
    return removed
