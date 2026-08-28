import datetime as dt
import os
import sqlite3

from lia.services.backup import backup_database, prune_old_backups


def _make_source_db(path):
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE t (v TEXT)")
    conn.execute("INSERT INTO t VALUES ('hola')")
    conn.commit()
    conn.close()


def test_backup_database_copies_data(tmp_path):
    source = tmp_path / "lia.db"
    _make_source_db(source)
    backup_dir = tmp_path / "backups"

    dest = backup_database(source, backup_dir, dt.datetime(2026, 8, 27, 10, 30, 0))

    assert dest.exists()
    conn = sqlite3.connect(str(dest))
    rows = conn.execute("SELECT v FROM t").fetchall()
    conn.close()
    assert rows == [("hola",)]


def test_prune_old_backups_removes_only_expired(tmp_path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    old = backup_dir / "lia-old.db"
    recent = backup_dir / "lia-recent.db"
    old.write_text("x")
    recent.write_text("x")

    now = dt.datetime(2026, 8, 27, 12, 0, 0)
    old_mtime = (now - dt.timedelta(days=10)).timestamp()
    recent_mtime = (now - dt.timedelta(hours=1)).timestamp()
    os.utime(old, (old_mtime, old_mtime))
    os.utime(recent, (recent_mtime, recent_mtime))

    removed = prune_old_backups(backup_dir, retention_days=7, now=now)

    assert removed == [old]
    assert not old.exists()
    assert recent.exists()


def test_prune_old_backups_missing_dir_returns_empty(tmp_path):
    assert prune_old_backups(tmp_path / "nope", retention_days=7, now=dt.datetime(2026, 8, 27)) == []
