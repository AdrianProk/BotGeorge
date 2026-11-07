"""Errors whose message is safe and meant to be shown to the Discord user."""

from __future__ import annotations


class UserFacingError(Exception):
    """An expected failure. `str(error)` is sent to the user as-is.

    Set `notify_owner=True` when the owner should hear about it too
    (for example when yt-dlp looks outdated).
    """

    def __init__(self, message: str, *, notify_owner: bool = False) -> None:
        super().__init__(message)
        self.notify_owner = notify_owner


DISCORD_MESSAGE_LIMIT = 2000


def truncate(text: str, limit: int = DISCORD_MESSAGE_LIMIT) -> str:
    """Cut `text` so it fits into one Discord message."""
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"
