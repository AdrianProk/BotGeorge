"""Random memes from Reddit.

Fetches the `hot` listing of a subreddit (cached for a few minutes), filters it
to safe, directly downloadable images/GIFs, and downloads one with a size cap.
Uses Reddit OAuth (app-only) when REDDIT_CLIENT_ID/SECRET are configured,
otherwise the public JSON endpoints.
"""

from __future__ import annotations

import asyncio
import html
import logging
import random
import time
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import quote, urlparse

import aiohttp

from george.errors import UserFacingError

log = logging.getLogger(__name__)

MEDIA_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4")
LISTING_TTL_S = 600
SUBREDDIT_ATTEMPTS = 3
DOWNLOAD_ATTEMPTS = 3


@dataclass(frozen=True, slots=True)
class MediaCandidate:
    post_id: str
    subreddit: str
    title: str
    url: str
    extension: str
    permalink: str
    nsfw: bool


@dataclass(frozen=True, slots=True)
class Meme:
    data: bytes
    filename: str
    subreddit: str
    title: str
    permalink: str


def _gallery_url(post: dict[str, Any]) -> str | None:
    metadata = post.get("media_metadata") or {}
    for item in (post.get("gallery_data") or {}).get("items") or []:
        media = metadata.get(item.get("media_id"), {})
        if media.get("status") != "valid":
            continue
        source = media.get("s") or {}
        url = source.get("gif") or source.get("u")
        if url:
            return url
    return None


def extract_media(post: dict[str, Any]) -> MediaCandidate | None:
    """Return a downloadable media candidate for a Reddit post, or None.

    Reddit-hosted videos (`is_video`) are skipped: their audio is a separate
    stream, so the downloadable file would be silent.
    """
    if post.get("stickied") or post.get("is_self") or post.get("is_video"):
        return None

    url = (
        _gallery_url(post)
        if post.get("is_gallery")
        else (post.get("url_overridden_by_dest") or post.get("url"))
    )
    if not url:
        return None
    url = html.unescape(url)

    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        return None
    path = parsed.path
    if path.lower().endswith(".gifv"):  # imgur's .gifv is an HTML page; the .mp4 is the media
        path = path[:-5] + ".mp4"
        url = parsed._replace(path=path).geturl()

    extension = PurePosixPath(path).suffix.lower()
    if extension not in MEDIA_EXTENSIONS:
        return None

    return MediaCandidate(
        post_id=str(post.get("id", "")),
        subreddit=str(post.get("subreddit", "")),
        title=str(post.get("title", "")),
        url=url,
        extension=".jpg" if extension == ".jpeg" else extension,
        permalink="https://www.reddit.com" + str(post.get("permalink", "")),
        nsfw=bool(post.get("over_18")),
    )


class RedditService:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        user_agent: str,
        client_id: str | None = None,
        client_secret: str | None = None,
        timeout_s: float = 10,
    ) -> None:
        self._session = session
        self._headers = {"User-Agent": user_agent}
        self._client_id = client_id
        self._client_secret = client_secret
        self._timeout = aiohttp.ClientTimeout(total=timeout_s)
        self._download_timeout = aiohttp.ClientTimeout(total=45, sock_read=15)
        self._listings: dict[str, tuple[float, list[dict[str, Any]]]] = {}
        self._recent: deque[str] = deque(maxlen=200)
        self._token: str | None = None
        self._token_expires = 0.0
        self._token_lock = asyncio.Lock()

    @property
    def uses_oauth(self) -> bool:
        return bool(self._client_id and self._client_secret)

    async def random_meme(
        self, subreddits: Sequence[str], *, allow_nsfw: bool, max_bytes: int
    ) -> Meme:
        subs = list(subreddits)
        random.shuffle(subs)
        for sub in subs[:SUBREDDIT_ATTEMPTS]:
            candidates = [
                c
                for c in (extract_media(p) for p in await self._listing(sub))
                if c is not None and (allow_nsfw or not c.nsfw) and c.post_id not in self._recent
            ]
            random.shuffle(candidates)
            for candidate in candidates[:DOWNLOAD_ATTEMPTS]:
                data = await self._download(candidate.url, max_bytes)
                if data is None:
                    continue
                self._recent.append(candidate.post_id)
                return Meme(
                    data=data,
                    filename=f"meme{candidate.extension}",
                    subreddit=candidate.subreddit or sub,
                    title=candidate.title,
                    permalink=candidate.permalink,
                )
        raise UserFacingError("I couldn't find a meme right now :( Try again in a moment.")

    async def _auth_headers(self) -> dict[str, str]:
        if not self.uses_oauth:
            return self._headers
        async with self._token_lock:
            if self._token is None or time.monotonic() > self._token_expires:
                async with self._session.post(
                    "https://www.reddit.com/api/v1/access_token",
                    data={"grant_type": "client_credentials"},
                    auth=aiohttp.BasicAuth(self._client_id or "", self._client_secret or ""),
                    headers=self._headers,
                    timeout=self._timeout,
                ) as resp:
                    resp.raise_for_status()
                    payload = await resp.json()
                self._token = payload["access_token"]
                self._token_expires = time.monotonic() + int(payload.get("expires_in", 3600)) - 60
        return {**self._headers, "Authorization": f"Bearer {self._token}"}

    async def _listing(self, sub: str) -> list[dict[str, Any]]:
        cached = self._listings.get(sub)
        if cached and time.monotonic() - cached[0] < LISTING_TTL_S:
            return cached[1]

        base = "https://oauth.reddit.com" if self.uses_oauth else "https://www.reddit.com"
        suffix = "" if self.uses_oauth else ".json"
        url = f"{base}/r/{quote(sub)}/hot{suffix}"
        try:
            headers = await self._auth_headers()
            async with self._session.get(
                url,
                params={"limit": "100", "raw_json": "1"},
                headers=headers,
                timeout=self._timeout,
            ) as resp:
                if resp.status != 200:
                    log.warning("Reddit listing r/%s returned HTTP %s", sub, resp.status)
                    return []
                payload = await resp.json()
        except (aiohttp.ClientError, TimeoutError, ValueError, KeyError) as exc:
            log.warning("Reddit listing r/%s failed: %r", sub, exc)
            return []

        posts = [child.get("data", {}) for child in payload.get("data", {}).get("children", [])]
        self._listings[sub] = (time.monotonic(), posts)
        return posts

    async def _download(self, url: str, max_bytes: int) -> bytes | None:
        try:
            async with self._session.get(
                url, headers=self._headers, timeout=self._download_timeout
            ) as resp:
                if resp.status != 200:
                    return None
                if resp.content_length and resp.content_length > max_bytes:
                    log.debug("Skipping %s: %d bytes is over the limit", url, resp.content_length)
                    return None
                chunks: list[bytes] = []
                size = 0
                async for chunk in resp.content.iter_chunked(64 * 1024):
                    size += len(chunk)
                    if size > max_bytes:
                        log.debug("Skipping %s: larger than %d bytes", url, max_bytes)
                        return None
                    chunks.append(chunk)
                return b"".join(chunks)
        except (aiohttp.ClientError, TimeoutError) as exc:
            log.warning("Meme download %s failed: %r", url, exc)
            return None
