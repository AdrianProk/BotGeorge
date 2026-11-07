"""YouTube → MP3 conversion.

The bot process never imports yt_dlp. Every job runs `george.services.ytdlp_worker`
in a fresh Python process, with the auto-updated yt-dlp (if any) first on
PYTHONPATH. So:

* a yt-dlp update takes effect with the next job, without restarting the bot;
* a hanging download can be killed (threads can't be);
* each job has its own temporary directory, and the number of parallel jobs is capped.

When a job fails because yt-dlp looks outdated, the updater is asked for a newer
version right away and the job is retried once.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import sys
import tempfile
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlparse

import george
from george.errors import UserFacingError

if TYPE_CHECKING:
    from george.services.ytdlp_updater import YtDlpUpdater

log = logging.getLogger(__name__)

YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}
SHORT_HOSTS = {"youtu.be", "www.youtu.be"}
PATH_STYLES = {"shorts", "live", "embed", "v"}
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
BITRATES_KBPS = (192, 160, 128, 96, 64)

# Folder that contains the `george` package, so the worker can import it even
# when the bot runs from a source checkout (George.py) without being installed.
PACKAGE_ROOT = Path(george.__file__).resolve().parent.parent

OUTDATED_HINT = (
    "YouTube changed something on their side and my downloader needs an update. "
    "The owner has been told. Try again later :("
)

# (substring in the lower-cased yt-dlp error, message for the user, notify owner?)
ERROR_HINTS: tuple[tuple[str, str, bool], ...] = (
    ("private video", "That video is private, I can't get it.", False),
    ("confirm your age", "That video is age-restricted, I can't get it.", False),
    ("age-restricted", "That video is age-restricted, I can't get it.", False),
    ("members-only", "That video is for channel members only.", False),
    ("join this channel", "That video is for channel members only.", False),
    ("not available in your country", "That video is blocked in my country.", False),
    ("blocked it in your country", "That video is blocked in my country.", False),
    ("premieres in", "That video hasn't premiered yet.", False),
    ("live event will begin", "That livestream hasn't started yet.", False),
    ("video unavailable", "That video is unavailable.", False),
    ("not a bot", "YouTube is blocking my requests right now. Try again later :(", True),
    ("nsig", OUTDATED_HINT, True),
    ("signature", OUTDATED_HINT, True),
    ("unable to extract", OUTDATED_HINT, True),
    ("requested format is not available", OUTDATED_HINT, True),
    ("http error 403", OUTDATED_HINT, True),
    ("javascript runtime", OUTDATED_HINT, True),
    ("please report this issue", OUTDATED_HINT, True),
)


class YtDlpOutdatedError(UserFacingError):
    """yt-dlp failed in a way that usually means YouTube changed and an update is needed."""

    def __init__(self, message: str = OUTDATED_HINT) -> None:
        super().__init__(message, notify_owner=True)


@dataclass(frozen=True, slots=True)
class Mp3Result:
    path: Path
    filename: str
    title: str
    duration_s: int
    bitrate_kbps: int
    ytdlp_version: str


def normalize_youtube_url(raw: str) -> str | None:
    """Return a canonical single-video URL, or None if `raw` isn't a YouTube video link.

    Playlist parameters are dropped, so `watch?v=X&list=Y` only fetches video X.
    """
    raw = raw.strip().strip("<>")
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        return None
    host = (parsed.hostname or "").lower()

    video_id: str | None = None
    if host in SHORT_HOSTS:
        video_id = parsed.path.strip("/").split("/")[0]
    elif host in YOUTUBE_HOSTS:
        if parsed.path.rstrip("/") == "/watch":
            video_id = parse_qs(parsed.query).get("v", [None])[0]
        else:
            parts = parsed.path.strip("/").split("/")
            if len(parts) >= 2 and parts[0] in PATH_STYLES:
                video_id = parts[1]

    if video_id and VIDEO_ID_RE.match(video_id):
        return f"https://www.youtube.com/watch?v={video_id}"
    return None


def choose_bitrate(duration_s: float, max_bytes: int, headroom: float = 0.9) -> int | None:
    """Highest standard MP3 bitrate whose output fits into `max_bytes`, or None."""
    if duration_s <= 0:
        return None
    budget_kbps = max_bytes * 8 * headroom / duration_s / 1000
    for kbps in BITRATES_KBPS:
        if kbps <= budget_kbps:
            return kbps
    return None


def safe_filename(title: str, extension: str = ".mp3") -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "", title)
    cleaned = " ".join(cleaned.split()).strip(" .")[:100]
    return (cleaned or "audio") + extension


def explain_download_error(message: str) -> UserFacingError:
    lowered = message.lower()
    for needle, text, notify in ERROR_HINTS:
        if needle in lowered:
            if text == OUTDATED_HINT:
                return YtDlpOutdatedError()
            return UserFacingError(text, notify_owner=notify)
    return UserFacingError(
        "The MP3 download failed. The link may be invalid or YouTube blocked the request."
    )


def format_duration(seconds: int) -> str:
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}:{secs:02d} min"


def error_from_worker(payload: dict[str, Any]) -> UserFacingError:
    message = str(payload.get("message") or "The conversion failed :(")
    if payload.get("outdated"):
        return YtDlpOutdatedError()
    return UserFacingError(message, notify_owner=bool(payload.get("notify_owner")))


class YouTubeService:
    def __init__(
        self,
        *,
        max_duration_s: int,
        max_concurrent: int,
        ffmpeg_location: str | None = None,
        job_timeout_s: float = 600,
        updater: YtDlpUpdater | None = None,
    ) -> None:
        self.max_duration_s = max_duration_s
        self._ffmpeg_location = ffmpeg_location
        self._job_timeout_s = job_timeout_s
        self.updater = updater
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._active = 0
        self._idle = asyncio.Event()
        self._idle.set()
        self.accepting = True

    @property
    def busy(self) -> bool:
        """True if a new job would have to wait for a free slot."""
        return self._semaphore.locked()

    @asynccontextmanager
    async def convert(
        self,
        url: str,
        *,
        max_bytes: int,
        on_update: Callable[[str], Awaitable[None]] | None = None,
    ) -> AsyncIterator[Mp3Result]:
        """Download `url` as MP3. The file is deleted when the `async with` block ends.

        `on_update(version)` is awaited if yt-dlp had to be updated during the job.
        """
        if not self.accepting:
            raise UserFacingError("I'm restarting right now. Try again in a minute.")
        tmp = Path(tempfile.mkdtemp(prefix="george-mp3-"))
        self._active += 1
        self._idle.clear()
        try:
            async with self._semaphore:
                try:
                    result = await self._run_job(url, tmp, max_bytes)
                except YtDlpOutdatedError:
                    new_version = (
                        await self.updater.update_if_available(forced=True)
                        if self.updater
                        else None
                    )
                    if not new_version:
                        raise
                    if on_update:
                        await on_update(new_version)
                    _empty_dir(tmp)
                    result = await self._run_job(url, tmp, max_bytes)
            yield result
        finally:
            self._active -= 1
            if self._active == 0:
                self._idle.set()
            shutil.rmtree(tmp, ignore_errors=True)

    async def drain(self, timeout_s: float) -> None:
        """Stop accepting jobs and wait for running ones (used on shutdown)."""
        self.accepting = False
        try:
            await asyncio.wait_for(self._idle.wait(), timeout_s)
        except TimeoutError:
            log.warning("Shutting down with %d MP3 job(s) still running", self._active)

    def _worker_env(self) -> dict[str, str]:
        env = os.environ.copy()
        overlay = self.updater.active_path() if self.updater else None
        paths = [str(p) for p in (overlay, PACKAGE_ROOT) if p]
        if env.get("PYTHONPATH"):
            paths.append(env["PYTHONPATH"])
        env["PYTHONPATH"] = os.pathsep.join(paths)
        env["PYTHONIOENCODING"] = "utf-8"
        return env

    async def _run_job(self, url: str, tmp: Path, max_bytes: int) -> Mp3Result:
        job = {
            "url": url,
            "tmp": str(tmp),
            "max_bytes": max_bytes,
            "max_duration_s": self.max_duration_s,
            "ffmpeg_location": self._ffmpeg_location,
        }
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "george.services.ytdlp_worker",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
            env=self._worker_env(),
        )
        try:
            _, err = await asyncio.wait_for(
                proc.communicate(json.dumps(job).encode()), self._job_timeout_s
            )
        except TimeoutError:
            proc.kill()
            await proc.wait()
            raise UserFacingError("That took way too long, so I gave up :(") from None
        except asyncio.CancelledError:
            proc.kill()
            await proc.wait()
            raise

        stderr = err.decode(errors="replace").strip()
        for line in stderr.splitlines():
            log.debug("worker: %s", line)

        result_file = tmp / "result.json"
        try:
            payload = json.loads(result_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            log.error(
                "MP3 worker exited with %s and no result: %s", proc.returncode, stderr[-2000:]
            )
            raise UserFacingError("The conversion crashed :( The error was logged.") from None

        if not payload.get("ok"):
            if payload.get("detail"):
                log.info("MP3 job for %s failed: %s", url, payload["detail"])
            raise error_from_worker(payload)

        return Mp3Result(
            path=Path(payload["path"]),
            filename=safe_filename(payload["title"]),
            title=payload["title"],
            duration_s=int(payload["duration_s"]),
            bitrate_kbps=int(payload["bitrate_kbps"]),
            ytdlp_version=str(payload.get("ytdlp_version", "?")),
        )


def _empty_dir(folder: Path) -> None:
    for child in folder.iterdir():
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            child.unlink(missing_ok=True)
