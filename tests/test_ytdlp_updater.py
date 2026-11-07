from __future__ import annotations

import json
import time

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

import fake_ytdlp
from george.errors import UserFacingError
from george.services.youtube import YouTubeService
from george.services.ytdlp_updater import YtDlpUpdater, version_key

CANONICAL_TEST_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
NEW = "2099.1.1"
CALLS = web.AppKey("calls", dict)
BROKEN = "2098.1.1"


def test_version_key_ordering():
    versions = ["2026.10.26", "2026.9.27.232945.dev0", "2026.11.5.232800.dev0", "2026.11.5"]
    assert sorted(versions, key=version_key) == [
        "2026.9.27.232945.dev0",
        "2026.10.26",
        "2026.11.5",
        "2026.11.5.232800.dev0",
    ]


def fake_pypi(
    latest: str, *, wheel: bytes | None = None, bad_hash: bool = False
) -> web.Application:
    """A minimal PyPI JSON API serving one yt-dlp release and its pinned yt-dlp-ejs."""
    yt_wheel = wheel if wheel is not None else fake_ytdlp.ytdlp_wheel(latest)
    ejs_wheel = fake_ytdlp.ejs_wheel("0.1.0")
    app = web.Application()
    calls = {"index": 0}

    def file_entry(request, name, data):
        return {
            "filename": name,
            "packagetype": "bdist_wheel",
            "url": str(request.url.with_path(f"/files/{name}").with_query(None)),
            "digests": {"sha256": "0" * 64 if bad_hash else fake_ytdlp.sha256(data)},
        }

    async def index(request):
        calls["index"] += 1
        return web.json_response(
            {"info": {"version": latest}, "releases": {latest: [{}], "2000.1.1": [{}]}}
        )

    async def release(request):
        return web.json_response(
            {
                "info": {"requires_dist": ['yt-dlp-ejs==0.1.0; extra == "default"']},
                "urls": [file_entry(request, f"yt_dlp-{latest}-py3-none-any.whl", yt_wheel)],
            }
        )

    async def ejs(request):
        return web.json_response(
            {
                "info": {},
                "urls": [file_entry(request, "yt_dlp_ejs-0.1.0-py3-none-any.whl", ejs_wheel)],
            }
        )

    async def files(request):
        name = request.match_info["name"]
        return web.Response(body=yt_wheel if name.startswith("yt_dlp-") else ejs_wheel)

    app.router.add_get("/pypi/yt-dlp/json", index)
    app.router.add_get(f"/pypi/yt-dlp/{latest}/json", release)
    app.router.add_get("/pypi/yt-dlp-ejs/0.1.0/json", ejs)
    app.router.add_get("/files/{name}", files)
    app[CALLS] = calls
    return app


def write_state(base, version):
    fake_ytdlp.install(base / version, version)
    (base / "state.json").write_text(json.dumps({"version": version, "dir": version}))


async def test_update_installs_verifies_and_switches(tmp_path):
    base = tmp_path / "yt-dlp"
    async with TestServer(fake_pypi(NEW)) as server:
        updater = YtDlpUpdater(base, index_url=str(server.make_url("/pypi")))
        assert updater.active_source == "bundled"

        assert await updater.update_if_available() == NEW
        assert updater.active_version == NEW
        assert updater.active_source == "auto-updated"
        assert (updater.active_path() / "yt_dlp" / "version.py").exists()
        assert (updater.active_path() / "yt_dlp_ejs" / "__init__.py").exists()
        assert json.loads((base / "state.json").read_text())["version"] == NEW

        # Already up to date now.
        assert await updater.update_if_available() is None

    # A restart picks the installed version up again.
    assert YtDlpUpdater(base).active_version == NEW


async def test_checksum_mismatch_keeps_current_version(tmp_path):
    async with TestServer(fake_pypi(NEW, bad_hash=True)) as server:
        updater = YtDlpUpdater(tmp_path / "yt-dlp", index_url=str(server.make_url("/pypi")))
        assert await updater.update_if_available() is None
        assert updater.active_source == "bundled"
        assert "Checksum" in updater.last_error


async def test_wheel_that_fails_test_import_is_not_used(tmp_path):
    broken = fake_ytdlp.ytdlp_wheel(NEW, reported_version="1.0")
    async with TestServer(fake_pypi(NEW, wheel=broken)) as server:
        updater = YtDlpUpdater(tmp_path / "yt-dlp", index_url=str(server.make_url("/pypi")))
        assert await updater.update_if_available() is None
        assert updater.active_source == "bundled"
        assert not (tmp_path / "yt-dlp" / NEW).exists()


async def test_forced_checks_are_rate_limited(tmp_path):
    app = fake_pypi("2000.1.1")  # older than the bundled yt-dlp: nothing to install
    async with TestServer(app) as server:
        updater = YtDlpUpdater(tmp_path / "yt-dlp", index_url=str(server.make_url("/pypi")))
        await updater.update_if_available(forced=True)
        await updater.update_if_available(forced=True)
        assert app[CALLS]["index"] == 1
        await updater.update_if_available()  # periodic/owner checks are not limited
        assert app[CALLS]["index"] == 2


async def test_disabled_updater_does_nothing(tmp_path):
    updater = YtDlpUpdater(tmp_path, enabled=False, index_url="http://127.0.0.1:9")
    assert await updater.update_if_available() is None


def test_overlay_older_than_bundled_is_ignored(tmp_path):
    write_state(tmp_path, "2000.1.1")
    updater = YtDlpUpdater(tmp_path)
    assert updater.active_source == "bundled"
    assert updater.active_path() is None


def test_missing_overlay_folder_is_ignored(tmp_path):
    (tmp_path / "state.json").write_text(json.dumps({"version": NEW, "dir": NEW}))
    assert YtDlpUpdater(tmp_path).active_source == "bundled"


# -- end to end: worker process + updater ---------------------------------------------


async def test_outdated_ytdlp_is_updated_and_job_retried(tmp_path):
    """The active yt-dlp is broken (like after a YouTube change). The job fails, the
    updater installs a fixed release, and the same job succeeds without a restart."""
    base = tmp_path / "yt-dlp"
    write_state(base, BROKEN)
    async with TestServer(fake_pypi(NEW)) as server:
        updater = YtDlpUpdater(base, index_url=str(server.make_url("/pypi")))
        assert updater.active_version == BROKEN
        service = YouTubeService(max_duration_s=900, max_concurrent=1, updater=updater)

        updates = []

        async def on_update(version):
            updates.append(version)

        async with service.convert(
            CANONICAL_TEST_URL, max_bytes=10 * 1024 * 1024, on_update=on_update
        ) as result:
            assert result.path.read_bytes() == b"ID3fake"
            assert result.filename == "Fake Title.mp3"
            assert result.ytdlp_version == NEW
            folder = result.path.parent
        assert updates == [NEW]
        assert not folder.exists()


async def test_outdated_without_newer_release_reports_error(tmp_path):
    base = tmp_path / "yt-dlp"
    write_state(base, BROKEN)
    async with TestServer(fake_pypi(BROKEN)) as server:
        updater = YtDlpUpdater(base, index_url=str(server.make_url("/pypi")))
        service = YouTubeService(max_duration_s=900, max_concurrent=1, updater=updater)
        with pytest.raises(UserFacingError) as info:
            async with service.convert(CANONICAL_TEST_URL, max_bytes=10_000_000):
                pass
        assert "update" in str(info.value)
        assert info.value.notify_owner


async def test_worker_errors_are_mapped(tmp_path):
    base = tmp_path / "yt-dlp"
    write_state(base, NEW)
    service = YouTubeService(max_duration_s=900, max_concurrent=1, updater=YtDlpUpdater(base))
    with pytest.raises(UserFacingError, match="private"):
        async with service.convert(CANONICAL_TEST_URL + "&private", max_bytes=10_000_000):
            pass
    with pytest.raises(UserFacingError, match="too long"):
        short = YouTubeService(max_duration_s=30, max_concurrent=1, updater=YtDlpUpdater(base))
        async with short.convert(CANONICAL_TEST_URL, max_bytes=10_000_000):
            pass


async def test_hanging_job_is_killed(tmp_path):
    base = tmp_path / "yt-dlp"
    write_state(base, NEW)
    service = YouTubeService(
        max_duration_s=900, max_concurrent=1, job_timeout_s=2, updater=YtDlpUpdater(base)
    )
    start = time.monotonic()
    with pytest.raises(UserFacingError, match="too long"):
        async with service.convert(CANONICAL_TEST_URL + "&slow", max_bytes=10_000_000):
            pass
    assert time.monotonic() - start < 15
