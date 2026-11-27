from __future__ import annotations

import json
from pathlib import Path

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from george.errors import UserFacingError
from george.services.reddit import RedditService, extract_media

FIXTURE = Path(__file__).parent / "fixtures" / "reddit_listing.json"


def posts() -> list[dict]:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return [child["data"] for child in data["data"]["children"]]


def by_id() -> dict:
    return {p["id"]: extract_media(p) for p in posts()}


def test_extract_media_filters():
    result = by_id()
    assert result["img1"].url == "https://i.redd.it/abc.jpeg"
    assert result["img1"].extension == ".jpg"
    assert result["nsfw1"].nsfw is True
    assert result["gifv1"].url == "https://i.imgur.com/abc.mp4"
    assert result["gal1"].url == "https://preview.redd.it/m2.jpg?width=640&format=pjpg&s=abc"
    for skipped in ("vid1", "self1", "sticky", "link1", "http1"):
        assert result[skipped] is None, skipped


@pytest.fixture
async def session():
    async with aiohttp.ClientSession() as s:
        yield s


async def test_random_meme_skips_nsfw_and_avoids_repeats(session, monkeypatch):
    service = RedditService(session, user_agent="test")

    async def fake_listing(sub):
        return posts()

    downloaded = []

    async def fake_download(url, max_bytes):
        downloaded.append(url)
        return b"data"

    monkeypatch.setattr(service, "_listing", fake_listing)
    monkeypatch.setattr(service, "_download", fake_download)

    seen = set()
    for _ in range(3):  # img1, gifv1, gal1 are the only safe candidates
        meme = await service.random_meme(["meme"], allow_nsfw=False, max_bytes=100)
        seen.add(meme.permalink)
    assert len(seen) == 3
    assert not any("nsfw" in url for url in downloaded)

    with pytest.raises(UserFacingError):  # everything safe was already posted
        await service.random_meme(["meme"], allow_nsfw=False, max_bytes=100)

    meme = await service.random_meme(["meme"], allow_nsfw=True, max_bytes=100)
    assert meme.filename == "meme.png"


async def test_download_respects_size_cap(session):
    async def small(request):
        return web.Response(body=b"x" * 100)

    async def big(request):
        return web.Response(body=b"x" * 5000)

    async def streamed(request):
        resp = web.StreamResponse()  # no Content-Length
        await resp.prepare(request)
        for _ in range(10):
            await resp.write(b"x" * 1000)
        await resp.write_eof()
        return resp

    app = web.Application()
    app.router.add_get("/small", small)
    app.router.add_get("/big", big)
    app.router.add_get("/streamed", streamed)
    async with TestServer(app) as server:
        service = RedditService(session, user_agent="test")
        assert await service._download(str(server.make_url("/small")), 1000) == b"x" * 100
        assert await service._download(str(server.make_url("/big")), 1000) is None
        assert await service._download(str(server.make_url("/streamed")), 1000) is None
        assert await service._download(str(server.make_url("/missing")), 1000) is None


async def test_listing_failure_returns_empty(session, monkeypatch):
    service = RedditService(session, user_agent="test")

    async def boom(*args, **kwargs):
        raise aiohttp.ClientConnectionError("down")

    monkeypatch.setattr(service, "_auth_headers", boom)
    assert await service._listing("meme") == []


def test_meme_api_posts_are_converted_and_filtered():
    from george.services.reddit import meme_api_to_posts

    payload = {
        "count": 3,
        "memes": [
            {
                "postLink": "https://redd.it/abc123",
                "subreddit": "meme",
                "title": "ok",
                "url": "https://i.redd.it/abc.png",
                "nsfw": False,
            },
            {
                "postLink": "https://redd.it/nsfw99",
                "subreddit": "meme",
                "title": "nope",
                "url": "https://i.redd.it/n.jpg",
                "nsfw": True,
            },
            {
                "postLink": "https://redd.it/txt",
                "subreddit": "meme",
                "title": "link",
                "url": "https://example.com/page",
                "nsfw": False,
            },
        ],
    }
    media = [extract_media(p) for p in meme_api_to_posts(payload)]
    assert media[0].post_id == "abc123"
    assert media[0].url == "https://i.redd.it/abc.png"
    assert media[0].subreddit == "meme"
    assert media[1].nsfw is True
    assert media[2] is None


async def test_listing_uses_meme_api_without_oauth(session, monkeypatch):
    import george.services.reddit as reddit

    async def gimme(request):
        assert request.match_info["sub"] == "meme"
        return web.json_response(
            {
                "memes": [
                    {
                        "postLink": "https://redd.it/x1",
                        "subreddit": "meme",
                        "title": "t",
                        "url": "https://i.redd.it/x1.jpg",
                        "nsfw": False,
                    }
                ]
            }
        )

    app = web.Application()
    app.router.add_get("/gimme/{sub}/50", gimme)
    async with TestServer(app) as server:
        monkeypatch.setattr(
            reddit, "MEME_API_URL", str(server.make_url("/gimme/")) + "{subreddit}/50"
        )
        service = RedditService(session, user_agent="test")
        posts = await service._listing("meme")
    assert [p["id"] for p in posts] == ["x1"]
