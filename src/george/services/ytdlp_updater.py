"""Keeps yt-dlp up to date while the bot is running.

When YouTube changes something, the yt-dlp version baked into the image stops
working until a newer release is installed. This updater closes that gap:

* It checks PyPI for a newer yt-dlp (on start, every few hours, and right after
  a download fails with an "outdated" error).
* It downloads the pure-Python wheels of yt-dlp and the matching yt-dlp-ejs,
  checks their SHA-256 against PyPI, unpacks them into DATA_DIR/yt-dlp/<version>,
  and test-imports them in a separate process.
* Only then does it switch over (an atomic write of `state.json`). Every MP3 job
  runs in its own Python process with that folder first on PYTHONPATH, so the
  next job uses the new version. No restart, no hot reloading.

If anything fails, the previous version (or the one bundled in the image) keeps
being used. The wheels are pure Python, so the folder works on every OS and CPU.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import io
import json
import logging
import os
import re
import shutil
import sys
import time
import zipfile
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as installed_version
from pathlib import Path
from typing import Any

import aiohttp

log = logging.getLogger(__name__)

DEFAULT_INDEX = "https://pypi.org/pypi"
EJS_PIN_RE = re.compile(r"^yt-dlp-ejs\s*==\s*([\w.]+)")
MIN_FORCED_INTERVAL_S = 30 * 60  # don't hammer PyPI when many downloads fail at once


def version_key(version: str) -> tuple[int, ...]:
    """Sortable key for yt-dlp versions like 2026.10.26 or 2026.11.5.232800.dev0."""
    return tuple(int(part) for part in re.findall(r"\d+", version.split("dev")[0]))


def bundled_version() -> str:
    try:
        return installed_version("yt-dlp")
    except PackageNotFoundError:
        return "0"


@dataclass(frozen=True, slots=True)
class WheelInfo:
    filename: str
    url: str
    sha256: str


class UpdateError(Exception):
    pass


class YtDlpUpdater:
    def __init__(
        self,
        base_dir: Path,
        *,
        channel: str = "stable",
        index_url: str = DEFAULT_INDEX,
        enabled: bool = True,
    ) -> None:
        self.base_dir = base_dir
        self.channel = channel
        self.index_url = index_url.rstrip("/")
        self.enabled = enabled
        self.bundled = bundled_version()
        self._overlay: Path | None = None
        self._overlay_version: str | None = None
        self._lock = asyncio.Lock()
        self._last_check: float | None = None  # monotonic time of the last check
        self.last_checked_at: float | None = None
        self.last_error: str | None = None
        self._load_state()

    # -- what is active right now -------------------------------------------------

    @property
    def state_file(self) -> Path:
        return self.base_dir / "state.json"

    @property
    def active_version(self) -> str:
        return self._overlay_version if self._overlay else self.bundled

    @property
    def active_source(self) -> str:
        return "auto-updated" if self._overlay else "bundled"

    def active_path(self) -> Path | None:
        """Folder to put first on PYTHONPATH, or None to use the bundled yt-dlp."""
        return self._overlay

    def _load_state(self) -> None:
        try:
            state = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        version = str(state.get("version", ""))
        folder = self.base_dir / str(state.get("dir", ""))
        if not version or not (folder / "yt_dlp").is_dir():
            return
        if version_key(version) <= version_key(self.bundled):
            log.info("Bundled yt-dlp %s is not older than auto-updated %s", self.bundled, version)
            return
        self._overlay, self._overlay_version = folder, version
        log.info("Using auto-updated yt-dlp %s from %s", version, folder)

    # -- checking and updating ---------------------------------------------------------

    async def update_if_available(self, *, forced: bool = False) -> str | None:
        """Install a newer yt-dlp if there is one. Returns the new version or None.

        `forced=True` is used after an "outdated" error; such checks are rate-limited.
        """
        if not self.enabled:
            return None
        async with self._lock:
            now = time.monotonic()
            if (
                forced
                and self._last_check is not None
                and now - self._last_check < MIN_FORCED_INTERVAL_S
            ):
                return None
            self._last_check = now
            self.last_checked_at = time.time()
            try:
                async with aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=120)
                ) as session:
                    latest = await self._latest_version(session)
                    if version_key(latest) <= version_key(self.active_version):
                        log.debug("yt-dlp %s is up to date", self.active_version)
                        self.last_error = None
                        return None
                    log.info("Updating yt-dlp %s → %s", self.active_version, latest)
                    await self._install(session, latest)
            except (UpdateError, aiohttp.ClientError, TimeoutError, OSError, ValueError) as exc:
                self.last_error = str(exc)
                log.warning("yt-dlp update check failed: %s", exc)
                return None
            self.last_error = None
            return latest

    async def _get_json(self, session: aiohttp.ClientSession, path: str) -> dict[str, Any]:
        async with session.get(f"{self.index_url}/{path}/json") as resp:
            if resp.status != 200:
                raise UpdateError(f"PyPI returned HTTP {resp.status} for {path}")
            return await resp.json()

    async def _latest_version(self, session: aiohttp.ClientSession) -> str:
        data = await self._get_json(session, "yt-dlp")
        if self.channel != "nightly":
            return str(data["info"]["version"])
        releases = [v for v, files in data.get("releases", {}).items() if files]
        if not releases:
            raise UpdateError("No yt-dlp releases found")
        return max(releases, key=version_key)

    @staticmethod
    def _pure_wheel(data: dict[str, Any]) -> WheelInfo:
        for file in data.get("urls", []):
            name = file.get("filename", "")
            if file.get("packagetype") == "bdist_wheel" and name.endswith("-py3-none-any.whl"):
                return WheelInfo(name, file["url"], file["digests"]["sha256"])
        raise UpdateError("No pure-Python wheel found")

    async def _download(self, session: aiohttp.ClientSession, wheel: WheelInfo) -> bytes:
        async with session.get(wheel.url) as resp:
            if resp.status != 200:
                raise UpdateError(f"Download of {wheel.filename} failed: HTTP {resp.status}")
            data = await resp.read()
        if hashlib.sha256(data).hexdigest() != wheel.sha256:
            raise UpdateError(f"Checksum mismatch for {wheel.filename}")
        return data

    async def _install(self, session: aiohttp.ClientSession, version: str) -> None:
        release = await self._get_json(session, f"yt-dlp/{version}")
        wheels = [self._pure_wheel(release)]

        # yt-dlp pins the yt-dlp-ejs version it needs (YouTube JS challenge solver).
        pins = [
            m.group(1)
            for req in release["info"].get("requires_dist") or []
            if (m := EJS_PIN_RE.match(req))
        ]
        if pins:
            wheels.append(self._pure_wheel(await self._get_json(session, f"yt-dlp-ejs/{pins[0]}")))

        payloads = [await self._download(session, w) for w in wheels]

        await asyncio.to_thread(self.base_dir.mkdir, parents=True, exist_ok=True)
        staging = self.base_dir / f".staging-{version}"
        await asyncio.to_thread(shutil.rmtree, staging, True)
        try:
            await asyncio.to_thread(_extract_wheels, payloads, staging)
            await self._verify(staging, version)
            target = self.base_dir / version
            await asyncio.to_thread(shutil.rmtree, target, True)
            await asyncio.to_thread(os.replace, staging, target)
        finally:
            await asyncio.to_thread(shutil.rmtree, staging, True)

        await asyncio.to_thread(self._write_state, version)
        previous = self._overlay
        self._overlay, self._overlay_version = target, version
        await asyncio.to_thread(self._cleanup, keep={target, previous})
        log.info("yt-dlp %s installed to %s", version, target)

    async def _verify(self, folder: Path, version: str) -> None:
        """Import the new yt-dlp in a fresh interpreter before switching to it."""
        env = {**os.environ, "PYTHONPATH": str(folder)}
        code = "import yt_dlp, yt_dlp.version; print(yt_dlp.version.__version__)"
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            code,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=60)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            raise UpdateError("Test import of the new yt-dlp timed out") from None
        got = out.decode(errors="replace").strip()
        if proc.returncode != 0 or version_key(got) != version_key(version):
            raise UpdateError(
                f"Test import failed (got {got!r}): {err.decode(errors='replace')[-300:]}"
            )

    def _write_state(self, version: str) -> None:
        state = {"version": version, "dir": version, "installed_at": int(time.time())}
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(state), encoding="utf-8")
        os.replace(tmp, self.state_file)

    def _cleanup(self, keep: set[Path | None]) -> None:
        """Remove old version folders, keeping the new one and the previous one
        (an MP3 job might still be running with it)."""
        for child in self.base_dir.iterdir():
            if child.is_dir() and child not in keep and not child.name.startswith(".staging"):
                with contextlib.suppress(OSError):
                    shutil.rmtree(child)


def _extract_wheels(payloads: list[bytes], target: Path) -> None:
    target.mkdir(parents=True)
    for data in payloads:
        with zipfile.ZipFile(io.BytesIO(data)) as wheel:
            for member in wheel.namelist():
                resolved = (target / member).resolve()
                if not resolved.is_relative_to(target.resolve()):
                    raise UpdateError(f"Unsafe path in wheel: {member}")
            wheel.extractall(target)
