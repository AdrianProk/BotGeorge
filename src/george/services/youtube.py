"""YouTube → MP3 conversion with yt-dlp.

This is the only module that imports yt_dlp, so yt-dlp updates can't break
anything else. Each job runs in its own temporary directory, the number of
parallel jobs is capped, and length/size limits are enforced *before* the
download starts.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import yt_dlp
from yt_dlp.utils import DownloadError

from george.errors import UserFacingError

log = logging.getLogger(__name__)

YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}
SHORT_HOSTS = {"youtu.be", "www.youtu.be"}
PATH_STYLES = {"shorts", "live", "embed", "v"}
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
BITRATES_KBPS = (192, 160, 128, 96, 64)

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
)


@dataclass(frozen=True, slots=True)
class Mp3Result:
    path: Path
    filename: str
    title: str
    duration_s: int
    bitrate_kbps: int


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
            return UserFacingError(text, notify_owner=notify)
    return UserFacingError(
        "The MP3 download failed. The link may be invalid or YouTube blocked the request."
    )


def format_duration(seconds: int) -> str:
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}:{secs:02d} min"


def yt_dlp_version() -> str:
    return yt_dlp.version.__version__


class _YtdlLogger:
    """Route yt-dlp's output into our logging instead of stdout."""

    def debug(self, msg: str) -> None:
        log.debug("yt-dlp: %s", msg)

    def info(self, msg: str) -> None:
        log.debug("yt-dlp: %s", msg)

    def warning(self, msg: str) -> None:
        log.info("yt-dlp: %s", msg)

    def error(self, msg: str) -> None:
        log.warning("yt-dlp: %s", msg)


class YouTubeService:
    def __init__(
        self,
        *,
        max_duration_s: int,
        max_concurrent: int,
        ffmpeg_location: str | None = None,
    ) -> None:
        self.max_duration_s = max_duration_s
        self._ffmpeg_location = ffmpeg_location
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
    async def convert(self, url: str, *, max_bytes: int) -> AsyncIterator[Mp3Result]:
        """Download `url` as MP3. The file is deleted when the `async with` block ends."""
        if not self.accepting:
            raise UserFacingError("I'm restarting right now. Try again in a minute.")
        tmp = Path(tempfile.mkdtemp(prefix="george-mp3-"))
        self._active += 1
        self._idle.clear()
        try:
            async with self._semaphore:
                result = await asyncio.to_thread(self._convert_blocking, url, tmp, max_bytes)
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

    # -- blocking part, runs in a worker thread ---------------------------------

    def _base_opts(self) -> dict[str, Any]:
        opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "noplaylist": True,
            "socket_timeout": 30,
            "retries": 3,
            "logger": _YtdlLogger(),
        }
        if self._ffmpeg_location:
            opts["ffmpeg_location"] = self._ffmpeg_location
        return opts

    def _convert_blocking(self, url: str, tmp: Path, max_bytes: int) -> Mp3Result:
        try:
            with yt_dlp.YoutubeDL(self._base_opts()) as ydl:
                info = ydl.extract_info(url, download=False)
        except DownloadError as exc:
            log.info("yt-dlp metadata error for %s: %s", url, exc)
            raise explain_download_error(str(exc)) from exc

        if not info or info.get("_type") == "playlist":
            raise UserFacingError("Please send a link to a single video, not a playlist.")
        if info.get("is_live") or info.get("live_status") in {
            "is_live",
            "is_upcoming",
            "post_live",
        }:
            raise UserFacingError("I can't convert livestreams, sorry.")

        duration = int(info.get("duration") or 0)
        if duration <= 0:
            raise UserFacingError("I couldn't work out how long that video is, so I won't risk it.")
        if duration > self.max_duration_s:
            raise UserFacingError(
                f"That video is too long ({format_duration(duration)}). "
                f"The limit is {format_duration(self.max_duration_s)}."
            )
        bitrate = choose_bitrate(duration, max_bytes)
        if bitrate is None:
            raise UserFacingError(
                f"That video is too long to fit this server's upload limit "
                f"({max_bytes // (1024 * 1024)} MB)."
            )

        opts = {
            **self._base_opts(),
            "format": "bestaudio/best",
            "outtmpl": str(tmp / "%(id)s.%(ext)s"),
            "writethumbnail": True,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": str(bitrate),
                },
                {"key": "FFmpegThumbnailsConvertor", "format": "jpg"},
                {"key": "EmbedThumbnail"},
                {"key": "FFmpegMetadata"},
            ],
            "postprocessor_args": {"EmbedThumbnail": ["-id3v2_version", "3"]},
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
        except DownloadError as exc:
            log.info("yt-dlp download error for %s: %s", url, exc)
            raise explain_download_error(str(exc)) from exc

        path = tmp / f"{info.get('id')}.mp3"
        if not path.is_file():
            found = sorted(tmp.glob("*.mp3"))
            if not found:
                raise UserFacingError("The conversion failed, I didn't get an MP3 file :(")
            path = found[0]

        size = path.stat().st_size
        if size > max_bytes:
            raise UserFacingError(
                f"The MP3 came out at {size / (1024 * 1024):.1f} MB, which is too big for "
                f"this server's upload limit ({max_bytes // (1024 * 1024)} MB)."
            )

        title = str(info.get("title") or "audio")
        return Mp3Result(
            path=path,
            filename=safe_filename(title),
            title=title,
            duration_s=duration,
            bitrate_kbps=bitrate,
        )
