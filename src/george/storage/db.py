"""SQLite connection, schema migrations and backups."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

log = logging.getLogger(__name__)

# Each entry is (version, SQL). Never edit an applied migration; append a new one.
MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        """
        CREATE TABLE entries (
            id              INTEGER PRIMARY KEY,
            category        TEXT NOT NULL
                            CHECK (category IN ('prompt', 'swear', 'compliment', 'random')),
            text            TEXT NOT NULL COLLATE NOCASE,
            author_id       INTEGER,          -- NULL for seed content
            origin_guild_id INTEGER,          -- server it was added from; NULL = seed / DM
            created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            UNIQUE (category, text)   -- case-insensitive thanks to COLLATE NOCASE
        );
        CREATE INDEX idx_entries_category ON entries (category);
        """,
    ),
]


class Database:
    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        self._conn: aiosqlite.Connection | None = None
        self.created = False  # True if the schema was created by this process
        self._backup_lock = asyncio.Lock()

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database is not connected")
        return self._conn

    async def connect(self) -> None:
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        for pragma in ("journal_mode=WAL", "busy_timeout=5000", "foreign_keys=ON"):
            async with self._conn.execute(f"PRAGMA {pragma}"):
                pass
        await self._migrate()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def _migrate(self) -> None:
        conn = self.conn
        await conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
        async with conn.execute("SELECT MAX(version) FROM schema_version") as cur:
            row = await cur.fetchone()
        current = row[0] or 0
        self.created = current == 0

        for version, sql in MIGRATIONS:
            if version <= current:
                continue
            log.info("Applying database migration %d", version)
            await conn.executescript(
                f"BEGIN;\n{sql}\nINSERT INTO schema_version VALUES ({version});\nCOMMIT;"
            )
        await conn.commit()

    async def backup(self, backup_dir: Path, keep: int, min_age_s: float = 0) -> Path | None:
        """Write a consistent copy of the database and prune old copies.

        Skipped (returns None) if the newest backup is younger than `min_age_s`,
        so frequent restarts don't push older backups out.
        """
        async with self._backup_lock:
            await asyncio.to_thread(backup_dir.mkdir, parents=True, exist_ok=True)
            newest = await asyncio.to_thread(_newest_backup_age, backup_dir)
            if newest is not None and newest < min_age_s:
                return None
            stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
            target = backup_dir / f"george-{stamp}.db"
            if await asyncio.to_thread(target.exists):
                return None
            async with self.conn.execute("VACUUM INTO ?", (str(target),)):
                pass
            await asyncio.to_thread(_prune_backups, backup_dir, keep)
            return target


def _newest_backup_age(backup_dir: Path) -> float | None:
    mtimes = [p.stat().st_mtime for p in backup_dir.glob("george-*.db")]
    return time.time() - max(mtimes) if mtimes else None


def _prune_backups(backup_dir: Path, keep: int) -> None:
    backups = sorted(backup_dir.glob("george-*.db"))
    for old in backups[:-keep]:
        old.unlink(missing_ok=True)
