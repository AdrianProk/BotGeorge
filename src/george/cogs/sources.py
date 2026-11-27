"""Find what a command should work on: the given argument, the command message,
or the message it replies to. Shared by the prefix/slash commands and the
right-click (context menu) commands."""

from __future__ import annotations

import re
from collections.abc import Callable

import discord
from discord.ext import commands

from george.services.youtube import normalize_youtube_url

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
URL_RE = re.compile(r"<?(https?://[^\s<>]+)>?")
CODE_BLOCK_RE = re.compile(r"```[^\n`]*\n(.*?)```", re.DOTALL)


def is_image(attachment: discord.Attachment) -> bool:
    content_type = attachment.content_type or ""
    return content_type.startswith("image/") or attachment.filename.lower().endswith(
        IMAGE_EXTENSIONS
    )


def is_text(attachment: discord.Attachment) -> bool:
    content_type = attachment.content_type or ""
    return attachment.filename.lower().endswith(".txt") or content_type.startswith("text/plain")


def first_attachment(
    message: discord.Message | None, accept: Callable[[discord.Attachment], bool]
) -> discord.Attachment | None:
    if message is None:
        return None
    return next((a for a in message.attachments if accept(a)), None)


async def replied_message(ctx: commands.Context) -> discord.Message | None:
    """The message the command message replies to (prefix commands only)."""
    if ctx.interaction is not None or ctx.message is None:
        return None
    ref = ctx.message.reference
    if ref is None or ref.message_id is None:
        return None
    if isinstance(ref.resolved, discord.Message):
        return ref.resolved
    try:
        return await ctx.channel.fetch_message(ref.message_id)
    except discord.HTTPException:
        return None


async def find_attachment(
    ctx: commands.Context,
    given: discord.Attachment | None,
    accept: Callable[[discord.Attachment], bool],
) -> discord.Attachment | None:
    """The attachment passed to the command, else one on the command message, else
    one on the message it replies to."""
    if given is not None:
        return given if accept(given) else None
    if ctx.interaction is None:
        found = first_attachment(ctx.message, accept)
        if found:
            return found
    return first_attachment(await replied_message(ctx), accept)


def find_youtube_url(text: str) -> str | None:
    """First YouTube video link in a piece of text, normalized."""
    for match in URL_RE.finditer(text or ""):
        url = normalize_youtube_url(match.group(1))
        if url:
            return url
    return None


def youtube_url_in_message(message: discord.Message) -> str | None:
    found = find_youtube_url(message.content)
    if found:
        return found
    for embed in message.embeds:
        if embed.url and (url := normalize_youtube_url(embed.url)):
            return url
    return None


def ascii_text_in_message(message: discord.Message) -> str | None:
    """ASCII art pasted into a message: the first code block, else the whole text
    if it has more than one line."""
    content = message.content or ""
    block = CODE_BLOCK_RE.search(content)
    if block and block.group(1).strip():
        return block.group(1)
    if content.count("\n") >= 1:
        return content
    return None


def qr_text_in_message(message: discord.Message) -> str | None:
    """What a QR code made from a message should contain: its text, else the link to
    its first attachment, else a link to the message itself."""
    if message.clean_content.strip():
        return message.clean_content
    if message.attachments:
        return message.attachments[0].url
    return message.jump_url
