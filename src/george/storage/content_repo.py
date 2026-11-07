"""Shared content lists (prompts, swears, compliments, random lines).

Content is shared between all servers. `origin_guild_id` and `author_id`
are stored only so entries can be traced and moderated.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Literal, get_args

from george.storage.db import Database

log = logging.getLogger(__name__)

Category = Literal["prompt", "swear", "compliment", "random"]
CATEGORIES: tuple[str, ...] = get_args(Category)

MAX_ENTRY_LENGTH = 300

# Keys used by the old data/Data.json file.
LEGACY_KEYS: dict[str, str] = {
    "Art prompts": "prompt",
    "Swears": "swear",
    "complement": "compliment",
    "Random": "random",
}


class DuplicateEntryError(Exception):
    pass


class InvalidEntryError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Entry:
    id: int
    category: str
    text: str
    author_id: int | None
    origin_guild_id: int | None
    created_at: str


def normalize_text(text: str) -> str:
    """Strip and validate user-submitted text. Raises InvalidEntryError."""
    cleaned = " ".join(text.split())
    if not cleaned:
        raise InvalidEntryError("The text can't be empty.")
    if len(cleaned) > MAX_ENTRY_LENGTH:
        raise InvalidEntryError(f"That's too long. Keep it under {MAX_ENTRY_LENGTH} characters.")
    return cleaned


class ContentRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def add(
        self,
        category: str,
        text: str,
        *,
        author_id: int | None,
        origin_guild_id: int | None,
    ) -> Entry:
        if category not in CATEGORIES:
            raise InvalidEntryError(f"Unknown category {category!r}")
        text = normalize_text(text)
        conn = self.db.conn
        try:
            async with conn.execute(
                "INSERT INTO entries (category, text, author_id, origin_guild_id) "
                "VALUES (?, ?, ?, ?) RETURNING *",
                (category, text, author_id, origin_guild_id),
            ) as cur:
                row = await cur.fetchone()
        except sqlite3.IntegrityError as exc:
            await conn.rollback()
            raise DuplicateEntryError(text) from exc
        await conn.commit()
        assert row is not None
        return Entry(**dict(row))

    async def random(self, category: str) -> str | None:
        async with self.db.conn.execute(
            "SELECT text FROM entries WHERE category = ? ORDER BY random() LIMIT 1",
            (category,),
        ) as cur:
            row = await cur.fetchone()
        return row["text"] if row else None

    async def get(self, entry_id: int) -> Entry | None:
        async with self.db.conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)) as cur:
            row = await cur.fetchone()
        return Entry(**dict(row)) if row else None

    async def list(self, category: str, *, limit: int = 20, offset: int = 0) -> list[Entry]:
        async with self.db.conn.execute(
            "SELECT * FROM entries WHERE category = ? ORDER BY id LIMIT ? OFFSET ?",
            (category, limit, offset),
        ) as cur:
            rows = await cur.fetchall()
        return [Entry(**dict(r)) for r in rows]

    async def count(self, category: str) -> int:
        async with self.db.conn.execute(
            "SELECT COUNT(*) FROM entries WHERE category = ?", (category,)
        ) as cur:
            row = await cur.fetchone()
        return int(row[0]) if row else 0

    async def delete(self, entry_id: int) -> bool:
        async with self.db.conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,)) as cur:
            deleted = cur.rowcount > 0
        await self.db.conn.commit()
        return deleted

    async def import_mapping(self, data: Mapping[str, Iterable[str]]) -> int:
        """Import lists keyed by category (new or legacy keys). Skips duplicates."""
        rows: list[tuple[str, str]] = []
        for key, texts in data.items():
            category = LEGACY_KEYS.get(key, key)
            if category not in CATEGORIES:
                continue  # e.g. the old "help" list
            for text in texts:
                try:
                    rows.append((category, normalize_text(str(text))))
                except InvalidEntryError:
                    continue

        conn = self.db.conn
        before = conn.total_changes
        for category, text in rows:
            async with conn.execute(
                "INSERT OR IGNORE INTO entries (category, text) VALUES (?, ?)", (category, text)
            ):
                pass
        await conn.commit()
        return conn.total_changes - before


def load_seed() -> dict[str, list[str]]:
    seed = resources.files("george.seed").joinpath("content.json")
    return json.loads(seed.read_text(encoding="utf-8"))


async def import_initial_content(repo: ContentRepo, data_dir: Path) -> None:
    """Fill a brand-new database with seed content and import a legacy Data.json."""
    if repo.db.created:
        added = await repo.import_mapping(load_seed())
        log.info("Seeded database with %d entries", added)

    legacy = data_dir / "Data.json"
    if legacy.is_file():
        try:
            data = json.loads(legacy.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.error("Could not import legacy %s: %s (file left untouched)", legacy, exc)
            return
        added = await repo.import_mapping(data)
        legacy.rename(legacy.with_name("Data.json.imported"))
        log.info("Imported %d entries from legacy %s", added, legacy)
