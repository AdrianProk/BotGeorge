"""One MP3 job, run as `python -m george.services.ytdlp_worker` in a separate process.

Reads the job as JSON from stdin and writes the outcome to `<tmp>/result.json`.
Because this runs in a fresh interpreter, it always imports whichever yt-dlp is
first on PYTHONPATH (the auto-updated one, if present). This is the only module
that imports yt_dlp.
"""

from __future__ import annotations

import json
import logging
import sys
import traceback
from pathlib import Path
from typing import Any

import yt_dlp
import yt_dlp.version
from yt_dlp.utils import DownloadError

from george.errors import UserFacingError
from george.services.youtube import (
    YtDlpOutdatedError,
    choose_bitrate,
    explain_download_error,
    format_duration,
)

log = logging.getLogger("george.worker")


class _YtdlLogger:
    """Route yt-dlp's output to stderr (the parent logs it) instead of stdout."""

    def debug(self, msg: str) -> None:
        if not msg.startswith("[debug] "):
            log.debug("%s", msg)

    def info(self, msg: str) -> None:
        log.debug("%s", msg)

    def warning(self, msg: str) -> None:
        log.info("%s", msg)

    def error(self, msg: str) -> None:
        log.warning("%s", msg)


def _base_opts(ffmpeg_location: str | None) -> dict[str, Any]:
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "socket_timeout": 30,
        "retries": 3,
        "logger": _YtdlLogger(),
    }
    if ffmpeg_location:
        opts["ffmpeg_location"] = ffmpeg_location
    return opts


def convert(
    url: str, tmp: Path, max_bytes: int, max_duration_s: int, ffmpeg_location: str | None
) -> dict[str, Any]:
    try:
        with yt_dlp.YoutubeDL(_base_opts(ffmpeg_location)) as ydl:
            info = ydl.extract_info(url, download=False)
    except DownloadError as exc:
        raise _with_detail(explain_download_error(str(exc)), exc) from exc

    if not info or info.get("_type") == "playlist":
        raise UserFacingError("Please send a link to a single video, not a playlist.")
    if info.get("is_live") or info.get("live_status") in {"is_live", "is_upcoming", "post_live"}:
        raise UserFacingError("I can't convert livestreams, sorry.")

    duration = int(info.get("duration") or 0)
    if duration <= 0:
        raise UserFacingError("I couldn't work out how long that video is, so I won't risk it.")
    if duration > max_duration_s:
        raise UserFacingError(
            f"That video is too long ({format_duration(duration)}). "
            f"The limit is {format_duration(max_duration_s)}."
        )
    bitrate = choose_bitrate(duration, max_bytes)
    if bitrate is None:
        raise UserFacingError(
            f"That video is too long to fit this server's upload limit "
            f"({max_bytes // (1024 * 1024)} MB)."
        )

    opts = {
        **_base_opts(ffmpeg_location),
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
        raise _with_detail(explain_download_error(str(exc)), exc) from exc

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

    return {
        "path": str(path),
        "title": str(info.get("title") or "audio"),
        "duration_s": duration,
        "bitrate_kbps": bitrate,
    }


def _with_detail(error: UserFacingError, cause: Exception) -> UserFacingError:
    error.detail = str(cause)[-1500:]  # type: ignore[attr-defined]
    return error


def main() -> int:
    logging.basicConfig(level=logging.DEBUG, stream=sys.stderr, format="%(message)s")
    job = json.loads(sys.stdin.read())
    tmp = Path(job["tmp"])
    result: dict[str, Any]
    try:
        data = convert(
            job["url"],
            tmp,
            int(job["max_bytes"]),
            int(job["max_duration_s"]),
            job.get("ffmpeg_location"),
        )
        result = {"ok": True, **data}
    except UserFacingError as exc:
        result = {
            "ok": False,
            "message": str(exc),
            "notify_owner": exc.notify_owner,
            "outdated": isinstance(exc, YtDlpOutdatedError),
            "detail": getattr(exc, "detail", None),
        }
    except Exception as exc:
        traceback.print_exc()
        # A crash inside yt-dlp itself is usually fixed by a newer release.
        in_ytdlp = any(
            "yt_dlp" in frame.filename for frame in traceback.extract_tb(exc.__traceback__)
        )
        result = {
            "ok": False,
            "message": "The conversion crashed :( The error was logged.",
            "notify_owner": True,
            "outdated": in_ytdlp,
            "detail": repr(exc),
        }
    result["ytdlp_version"] = yt_dlp.version.__version__
    (tmp / "result.json").write_text(json.dumps(result), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
