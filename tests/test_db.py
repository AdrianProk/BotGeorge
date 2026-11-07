from __future__ import annotations

import sqlite3

from george.storage.db import MIGRATIONS


async def test_migrations_are_recorded(db):
    async with db.conn.execute("SELECT MAX(version) FROM schema_version") as cur:
        assert (await cur.fetchone())[0] == MIGRATIONS[-1][0]


async def test_backup_creates_copy_and_prunes(db, tmp_path):
    backups = tmp_path / "backups"
    for i in range(3):
        (backups).mkdir(exist_ok=True)
        (backups / f"george-2020010{i}-000000.db").write_bytes(b"old")
    path = await db.backup(backups, keep=2)
    assert path is not None and path.exists()
    with sqlite3.connect(path) as copy:
        assert copy.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0] >= 1
    assert len(list(backups.glob("george-*.db"))) == 2


async def test_backup_skipped_when_recent(db, tmp_path):
    backups = tmp_path / "backups"
    assert await db.backup(backups, keep=5) is not None
    assert await db.backup(backups, keep=5, min_age_s=3600) is None
