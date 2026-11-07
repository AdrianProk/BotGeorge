from __future__ import annotations

import asyncio

import pytest

from george.errors import UserFacingError
from george.services.youtube import (
    OUTDATED_HINT,
    Mp3Result,
    YouTubeService,
    choose_bitrate,
    explain_download_error,
    normalize_youtube_url,
    safe_filename,
)

VID = "dQw4w9WgXcQ"
CANON = f"https://www.youtube.com/watch?v={VID}"


@pytest.mark.parametrize(
    "url",
    [
        f"https://www.youtube.com/watch?v={VID}",
        f"https://youtube.com/watch?v={VID}&t=42",
        f"https://m.youtube.com/watch?v={VID}",
        f"https://music.youtube.com/watch?v={VID}&feature=share",
        f"https://www.youtube.com/watch?v={VID}&list=PL1234567890",
        f"https://youtu.be/{VID}",
        f"https://youtu.be/{VID}?si=abcdef",
        f"https://www.youtube.com/shorts/{VID}",
        f"https://www.youtube.com/live/{VID}",
        f"<https://youtu.be/{VID}>",
        f"  http://www.youtube.com/watch?v={VID}  ",
    ],
)
def test_valid_urls_are_normalized(url):
    assert normalize_youtube_url(url) == CANON


@pytest.mark.parametrize(
    "url",
    [
        "",
        "not a link",
        "https://www.youtube.com/playlist?list=PL1234567890",
        "https://www.youtube.com/@somechannel",
        "https://www.youtube.com/watch?v=short",
        f"https://evil.example/watch?v={VID}",
        f"https://youtube.com.evil.example/watch?v={VID}",
        f"ftp://youtu.be/{VID}",
    ],
)
def test_invalid_urls(url):
    assert normalize_youtube_url(url) is None


def test_choose_bitrate():
    ten_mb = 10 * 1024 * 1024
    assert choose_bitrate(180, ten_mb) == 192  # 3 min fits easily
    assert choose_bitrate(600, ten_mb) == 96  # 10 min
    assert choose_bitrate(15 * 60, ten_mb) == 64
    assert choose_bitrate(60 * 60, ten_mb) is None  # 1 h doesn't fit
    assert choose_bitrate(0, ten_mb) is None


def test_safe_filename():
    assert safe_filename('AC/DC: "Back" <in> Black?') == "ACDC Back in Black.mp3"
    assert safe_filename("...") == "audio.mp3"
    assert len(safe_filename("x" * 500)) == 104


@pytest.mark.parametrize(
    ("message", "expected", "notify"),
    [
        ("ERROR: [youtube] x: Private video. Sign in", "private", False),
        ("ERROR: Sign in to confirm your age", "age-restricted", False),
        ("ERROR: Sign in to confirm you're not a bot", "blocking", True),
        ("ERROR: nsig extraction failed", OUTDATED_HINT, True),
        ("ERROR: Requested format is not available", OUTDATED_HINT, True),
        ("ERROR: something new and weird", "download failed", False),
    ],
)
def test_error_mapping(message, expected, notify):
    err = explain_download_error(message)
    assert expected.lower() in str(err).lower()
    assert err.notify_owner is notify


async def test_convert_cleans_up_and_limits_concurrency(monkeypatch):
    service = YouTubeService(max_duration_s=900, max_concurrent=1)
    running = 0
    peak = 0
    seen_dirs = []

    async def fake_job(url, tmp, max_bytes):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        seen_dirs.append(tmp)
        out = tmp / "x.mp3"
        out.write_bytes(b"ID3")
        await asyncio.sleep(0.05)
        running -= 1
        return Mp3Result(out, "x.mp3", "x", 60, 192, "test")

    monkeypatch.setattr(service, "_run_job", fake_job)

    async def job():
        async with service.convert(CANON, max_bytes=1000) as result:
            assert result.path.exists()

    await asyncio.gather(job(), job(), job())
    assert peak == 1
    assert len(set(seen_dirs)) == 3  # every job had its own directory
    assert not any(d.exists() for d in seen_dirs)  # and it was removed


async def test_convert_refused_while_draining():
    service = YouTubeService(max_duration_s=900, max_concurrent=1)
    await service.drain(timeout_s=0.1)
    with pytest.raises(UserFacingError):
        async with service.convert(CANON, max_bytes=1000):
            pass
