"""A tiny stand-in for the yt_dlp package, used to test the worker and the updater offline.

Versions starting with 2098 behave like an outdated yt-dlp (nsig error);
other versions "download" a fake MP3.
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

INIT = """
import time
from . import utils, version


class YoutubeDL:
    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=True):
        if version.__version__.startswith("2098"):
            raise utils.DownloadError("ERROR: [youtube] abc: nsig extraction failed")
        if "slow" in url:
            time.sleep(30)
        if "private" in url:
            raise utils.DownloadError("ERROR: [youtube] abc: Private video. Sign in")
        info = {"id": "abc", "title": "Fake / Title", "duration": 60}
        if download:
            path = self.opts["outtmpl"].replace("%(id)s", "abc").replace("%(ext)s", "mp3")
            with open(path, "wb") as f:
                f.write(b"ID3fake")
        return info
"""


def sources(version: str, reported_version: str | None = None) -> dict[str, str]:
    return {
        "yt_dlp/__init__.py": INIT,
        "yt_dlp/utils.py": "class DownloadError(Exception):\n    pass\n",
        "yt_dlp/version.py": f"__version__ = {reported_version or version!r}\n",
        f"yt_dlp-{version}.dist-info/METADATA": f"Name: yt-dlp\nVersion: {version}\n",
    }


def install(folder: Path, version: str) -> Path:
    """Write the fake package into `folder` (like an unpacked wheel)."""
    for name, text in sources(version).items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return folder


def wheel(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, text in files.items():
            zf.writestr(name, text)
    return buf.getvalue()


def ytdlp_wheel(version: str, reported_version: str | None = None) -> bytes:
    return wheel(sources(version, reported_version))


def ejs_wheel(version: str) -> bytes:
    return wheel(
        {
            "yt_dlp_ejs/__init__.py": "",
            f"yt_dlp_ejs-{version}.dist-info/METADATA": f"Name: yt-dlp-ejs\nVersion: {version}\n",
        }
    )


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
