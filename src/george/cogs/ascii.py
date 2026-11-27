"""Image → ASCII art (.txt) and back."""

from __future__ import annotations

import asyncio
import io
from typing import TYPE_CHECKING, Literal

import discord
from discord import app_commands
from discord.ext import commands

from george.bot import upload_limit
from george.errors import UserFacingError
from george.services import ascii_art

if TYPE_CHECKING:
    from collections.abc import Callable

    from george.bot import GeorgeBot

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")


def is_image(attachment: discord.Attachment) -> bool:
    content_type = attachment.content_type or ""
    return content_type.startswith("image/") or attachment.filename.lower().endswith(
        IMAGE_EXTENSIONS
    )


def is_text(attachment: discord.Attachment) -> bool:
    content_type = attachment.content_type or ""
    return attachment.filename.lower().endswith(".txt") or content_type.startswith("text/plain")


async def find_attachment(
    ctx: commands.Context,
    given: discord.Attachment | None,
    accept: Callable[[discord.Attachment], bool],
) -> discord.Attachment | None:
    """The attachment passed to the command, else one on the message, else one on the
    message it replies to (so you can reply to someone's picture with `$ascii`)."""
    if given is not None:
        return given if accept(given) else None
    candidates: list[discord.Attachment] = []
    message = ctx.message
    if ctx.interaction is None and message is not None:
        candidates.extend(message.attachments)
        ref = message.reference
        if ref is not None and ref.message_id is not None:
            replied = ref.resolved
            if not isinstance(replied, discord.Message):
                try:
                    replied = await ctx.channel.fetch_message(ref.message_id)
                except discord.HTTPException:
                    replied = None
            if isinstance(replied, discord.Message):
                candidates.extend(replied.attachments)
    return next((a for a in candidates if accept(a)), None)


class Ascii(commands.Cog):
    def __init__(self, bot: GeorgeBot) -> None:
        self.bot = bot

    @commands.hybrid_command(
        name="ascii",
        description="I turn your image into ASCII art (.txt)",
    )
    @app_commands.describe(
        image="The picture (or reply to a message with a picture)",
        width=f"Characters per line ({ascii_art.MIN_WIDTH}-{ascii_art.MAX_WIDTH}, default {ascii_art.DEFAULT_WIDTH})",
        invert="Light characters on a dark background (looks right in Discord's dark theme)",
    )
    @commands.cooldown(3, 30, commands.BucketType.user)
    async def ascii(
        self,
        ctx: commands.Context,
        image: discord.Attachment | None = None,
        width: commands.Range[
            int, ascii_art.MIN_WIDTH, ascii_art.MAX_WIDTH
        ] = ascii_art.DEFAULT_WIDTH,
        invert: bool = False,
    ) -> None:
        attachment = await find_attachment(ctx, image, is_image)
        if attachment is None:
            raise UserFacingError(
                "Give me a picture: attach one to the command, or reply to a message with a picture."
            )
        if attachment.size > ascii_art.MAX_IMAGE_BYTES:
            raise UserFacingError(
                f"That image is too big (max {ascii_art.MAX_IMAGE_BYTES // (1024 * 1024)} MB)."
            )

        async with ctx.typing():
            data = await attachment.read()
            text = await asyncio.to_thread(
                ascii_art.image_to_ascii, data, width=width, invert=invert
            )

        lines = text.splitlines()
        cols = max((len(line) for line in lines), default=0)
        message = f"Here is your ASCII art :) ({cols}×{len(lines)} characters)"
        preview = f"\n```\n{text}```"
        if len(message) + len(preview) <= 2000:
            message += preview
        await ctx.send(
            message,
            file=discord.File(
                io.BytesIO(text.encode("utf-8")),
                filename=ascii_art.output_name(attachment.filename, "-ascii.txt"),
            ),
        )

    @commands.hybrid_command(
        name="asciiimage",
        aliases=["fromascii"],
        description="I turn an ASCII art .txt back into a picture",
    )
    @app_commands.describe(
        file="The .txt file (or reply to a message with one)",
        style="smooth = like a picture, blocks = pixel blocks, text = the characters themselves",
        invert="The art is light characters on a dark background",
    )
    @commands.cooldown(3, 30, commands.BucketType.user)
    async def asciiimage(
        self,
        ctx: commands.Context,
        file: discord.Attachment | None = None,
        style: Literal["smooth", "blocks", "text"] = "smooth",
        invert: bool = False,
    ) -> None:
        attachment = await find_attachment(ctx, file, is_text)
        if attachment is None:
            raise UserFacingError(
                "Give me an ASCII art .txt file: attach it to the command, or reply to a message with one."
            )
        if attachment.size > ascii_art.MAX_TEXT_BYTES:
            raise UserFacingError(
                f"That file is too big (max {ascii_art.MAX_TEXT_BYTES // 1024} KB)."
            )

        async with ctx.typing():
            text = ascii_art.decode_text(await attachment.read())
            png = await asyncio.to_thread(
                ascii_art.ascii_to_image, text, style=style, invert=invert
            )
        if len(png) > upload_limit(ctx):
            raise UserFacingError("The picture came out too big for this server's upload limit :(")
        await ctx.send(
            "Here is your picture :)",
            file=discord.File(
                io.BytesIO(png), filename=ascii_art.output_name(attachment.filename, ".png")
            ),
        )


async def setup(bot: GeorgeBot) -> None:
    await bot.add_cog(Ascii(bot))
