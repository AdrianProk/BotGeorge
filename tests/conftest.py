from __future__ import annotations

import pytest

from george.storage.content_repo import ContentRepo
from george.storage.db import Database


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "test.db")
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
async def repo(db):
    return ContentRepo(db)
