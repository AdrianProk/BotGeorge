from __future__ import annotations

import json

import pytest

from george.storage.content_repo import (
    MAX_ENTRY_LENGTH,
    DuplicateEntryError,
    InvalidEntryError,
    import_initial_content,
    load_seed,
)
from george.storage.db import Database


async def test_add_and_random(repo):
    entry = await repo.add("prompt", "  a   goose  ", author_id=1, origin_guild_id=2)
    assert entry.text == "a goose"
    assert entry.author_id == 1
    assert entry.origin_guild_id == 2
    assert await repo.random("prompt") == "a goose"


async def test_random_on_empty_category_returns_none(repo):
    assert await repo.random("swear") is None


async def test_duplicates_are_rejected_case_insensitively(repo):
    await repo.add("swear", "You stink", author_id=1, origin_guild_id=None)
    with pytest.raises(DuplicateEntryError):
        await repo.add("swear", "you STINK", author_id=2, origin_guild_id=None)
    # Same text in another category is fine.
    await repo.add("random", "You stink", author_id=1, origin_guild_id=None)


async def test_content_is_shared_between_servers(repo):
    await repo.add("compliment", "nice hat", author_id=1, origin_guild_id=111)
    # Read without any server filter: every server gets the same list.
    assert await repo.random("compliment") == "nice hat"


@pytest.mark.parametrize("text", ["", "   ", "x" * (MAX_ENTRY_LENGTH + 1)])
async def test_invalid_text(repo, text):
    with pytest.raises(InvalidEntryError):
        await repo.add("prompt", text, author_id=1, origin_guild_id=None)


async def test_invalid_category(repo):
    with pytest.raises(InvalidEntryError):
        await repo.add("help", "x", author_id=1, origin_guild_id=None)


async def test_list_count_get_delete(repo):
    ids = [
        (await repo.add("random", f"line {i}", author_id=1, origin_guild_id=None)).id
        for i in range(5)
    ]
    assert await repo.count("random") == 5
    page = await repo.list("random", limit=2, offset=2)
    assert [e.text for e in page] == ["line 2", "line 3"]
    assert (await repo.get(ids[0])).text == "line 0"
    assert await repo.delete(ids[0]) is True
    assert await repo.delete(ids[0]) is False
    assert await repo.get(ids[0]) is None
    assert await repo.count("random") == 4


async def test_import_mapping_handles_legacy_keys_and_skips_help(repo):
    added = await repo.import_mapping(
        {
            "Art prompts": ["Goose", "goose", ""],
            "Swears": ["Fuck you"],
            "complement": ["you smell nice"],
            "Random": ["Sleep is for the weak"],
            "help": ["my Commands are:"],
        }
    )
    assert added == 4
    assert await repo.count("prompt") == 1


async def test_seed_file_is_valid():
    seed = load_seed()
    assert set(seed) == {"prompt", "swear", "compliment", "random"}
    assert all(seed.values())


async def test_initial_import_seeds_new_db_and_imports_legacy_file(tmp_path):
    (tmp_path / "Data.json").write_text(
        json.dumps({"Art prompts": ["A brand new prompt", "Goose"], "help": ["x"]}),
        encoding="utf-8",
    )
    db = Database(tmp_path / "george.db")
    await db.connect()
    from george.storage.content_repo import ContentRepo

    repo = ContentRepo(db)
    await import_initial_content(repo, tmp_path)
    seed_prompts = len(load_seed()["prompt"])
    assert await repo.count("prompt") == seed_prompts + 1  # "Goose" is already in the seed
    assert not (tmp_path / "Data.json").exists()
    assert (tmp_path / "Data.json.imported").exists()
    await db.close()

    # Second start: no re-seed, nothing duplicated.
    db = Database(tmp_path / "george.db")
    await db.connect()
    assert db.created is False
    await import_initial_content(ContentRepo(db), tmp_path)
    assert await ContentRepo(db).count("prompt") == seed_prompts + 1
    await db.close()


async def test_corrupt_legacy_file_is_left_alone(tmp_path, repo):
    (tmp_path / "Data.json").write_text("{not json", encoding="utf-8")
    await import_initial_content(repo, tmp_path)
    assert (tmp_path / "Data.json").read_text(encoding="utf-8") == "{not json"
