"""Image → ASCII art (.txt) and back, as commands and right-click (Apps) menu entries."""

from __future__ import annotations

import asyncio
import io
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, Literal

import discord
from discord import app_commands
from discord.ext import commands

from george.bot import guild_upload_limit, upload_limit
from george.cogs.sources import (
    ascii_text_in_message,
    find_attachment,
    first_attachment,
    is_image,
    is_text,
    replied_message,
)
from george.errors import UserFacingError
from george.services import ascii_art

if TYPE_CHECKING:
    from george.bot import GeorgeBot

Send = Callable[..., Awaitable[Any]]
AVATAR_SIZE = 256


async def avatar_bytes(user: discord.abc.User) -> tuple[bytes, str]:
    """The user's avatar (animated avatars stay animated) and a file name for it."""
    asset = user.display_avatar.with_size(AVATAR_SIZE)
    if not asset.is_animated():
        asset = asset.with_static_format("png")
    data = await asset.read()
    return data, f"{user.name}-avatar.{'gif' if asset.is_animated() else 'png'}"


class Ascii(commands.Cog):
    def __init__(self, bot: GeorgeBot) -> None:
        self.bot = bot
        self.menus = [
            app_commands.ContextMenu(name="Make ASCII art", callback=self.ascii_menu),
            app_commands.ContextMenu(name="ASCII art to picture", callback=self.picture_menu),
            app_commands.ContextMenu(name="ASCII avatar", callback=self.avatar_menu),
        ]

    async def cog_load(self) -> None:
        for menu in self.menus:
            self.bot.tree.add_command(menu)

    async def cog_unload(self) -> None:
        for menu in self.menus:
            self.bot.tree.remove_command(menu.name, type=menu.type)

    # -- shared work ---------------------------------------------------------------------

    async def send_ascii(
        self, send: Send, data: bytes, filename: str, *, width: int, invert: bool, max_bytes: int
    ) -> None:
        frames = await asyncio.to_thread(
            ascii_art.image_to_ascii_frames, data, width=width, invert=invert
        )
        text = ascii_art.format_frames(frames)
        cols = max((len(line) for f in frames for line in f.lines), default=0)
        rows = len(frames[0].lines)
        txt = text.encode("utf-8")
        if len(txt) > max_bytes:
            raise UserFacingError("The ASCII art came out too big for this server's upload limit.")
        files = [discord.File(io.BytesIO(txt), ascii_art.output_name(filename, "-ascii.txt"))]

        if len(frames) > 1:
            gif = await asyncio.to_thread(ascii_art.render_ascii, text, style="text", invert=invert)
            message = (
                f"Here is your animated ASCII art :) "
                f"({len(frames)} frames, {cols}×{rows} characters each)"
            )
            if len(txt) + len(gif.data) <= max_bytes:
                files.append(
                    discord.File(
                        io.BytesIO(gif.data), ascii_art.output_name(filename, "-ascii.gif")
                    )
                )
            else:
                message += (
                    "\n(The animated preview was too big to upload, but the .txt has every frame.)"
                )
        else:
            message = f"Here is your ASCII art :) ({cols}×{rows} characters)"
            preview = f"\n```\n{text}```"
            if len(message) + len(preview) <= 2000:
                message += preview
        await send(message, files=files)

    async def send_picture(
        self, send: Send, text: str, filename: str, *, style: str, invert: bool, max_bytes: int
    ) -> None:
        rendered = await asyncio.to_thread(ascii_art.render_ascii, text, style=style, invert=invert)
        if len(rendered.data) > max_bytes:
            raise UserFacingError("The picture came out too big for this server's upload limit :(")
        message = (
            f"Here is your animation :) ({rendered.frames} frames)"
            if rendered.frames > 1
            else "Here is your picture :)"
        )
        await send(
            message,
            file=discord.File(
                io.BytesIO(rendered.data), ascii_art.output_name(filename, rendered.extension)
            ),
        )

    @staticmethod
    async def read_image(attachment: discord.Attachment) -> bytes:
        if attachment.size > ascii_art.MAX_IMAGE_BYTES:
            raise UserFacingError(
                f"That image is too big (max {ascii_art.MAX_IMAGE_BYTES // (1024 * 1024)} MB)."
            )
        return await attachment.read()

    @staticmethod
    async def read_text(attachment: discord.Attachment) -> str:
        if attachment.size > ascii_art.MAX_TEXT_BYTES:
            raise UserFacingError(
                f"That file is too big (max {ascii_art.MAX_TEXT_BYTES // 1024} KB)."
            )
        return ascii_art.decode_text(await attachment.read())

    # -- commands ------------------------------------------------------------------------

    @commands.hybrid_command(
        name="ascii",
        description="I turn an image or someone's avatar into ASCII art (.txt)",
    )
    @app_commands.describe(
        image="The picture (or reply to a message with a picture)",
        user="Use this person's avatar instead",
        width=f"Characters per line ({ascii_art.MIN_WIDTH}-{ascii_art.MAX_WIDTH}, default {ascii_art.DEFAULT_WIDTH})",
        invert="Light characters on a dark background (looks right in Discord's dark theme)",
    )
    @commands.cooldown(3, 30, commands.BucketType.user)
    async def ascii(
        self,
        ctx: commands.Context,
        image: discord.Attachment | None = None,
        user: discord.User | None = None,
        width: commands.Range[
            int, ascii_art.MIN_WIDTH, ascii_art.MAX_WIDTH
        ] = ascii_art.DEFAULT_WIDTH,
        invert: bool = False,
    ) -> None:
        if image is None and user is not None:
            async with ctx.typing():
                data, filename = await avatar_bytes(user)
                await self.send_ascii(
                    ctx.send,
                    data,
                    filename,
                    width=width,
                    invert=invert,
                    max_bytes=upload_limit(ctx),
                )
            return

        attachment = await find_attachment(ctx, image, is_image)
        if attachment is None:
            raise UserFacingError(
                "Give me a picture: attach one, reply to a message with one, "
                "or mention someone to use their avatar."
            )
        async with ctx.typing():
            data = await self.read_image(attachment)
            await self.send_ascii(
                ctx.send,
                data,
                attachment.filename,
                width=width,
                invert=invert,
                max_bytes=upload_limit(ctx),
            )

    @commands.hybrid_command(
        name="asciiimage",
        aliases=["fromascii"],
        description="I turn ASCII art (.txt or a code block) back into a picture",
    )
    @app_commands.describe(
        file="The .txt file (or reply to a message with a .txt or a code block)",
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
        text: str | None = None
        filename = "ascii.txt"
        if attachment is not None:
            text, filename = await self.read_text(attachment), attachment.filename
        elif (replied := await replied_message(ctx)) is not None:
            text = ascii_text_in_message(replied)
        if text is None:
            raise UserFacingError(
                "Give me ASCII art: attach a .txt, or reply to a message with a .txt or a code block."
            )
        async with ctx.typing():
            await self.send_picture(
                ctx.send, text, filename, style=style, invert=invert, max_bytes=upload_limit(ctx)
            )

    # -- right-click menu (Apps) -----------------------------------------------------------

    @app_commands.checks.cooldown(3, 30, key=lambda i: i.user.id)
    async def ascii_menu(self, interaction: discord.Interaction, message: discord.Message) -> None:
        attachment = first_attachment(message, is_image)
        if attachment is None:
            raise UserFacingError("That message has no picture I could turn into ASCII art.")
        await interaction.response.defer(thinking=True)
        data = await self.read_image(attachment)
        await self.send_ascii(
            interaction.followup.send,
            data,
            attachment.filename,
            width=ascii_art.DEFAULT_WIDTH,
            invert=False,
            max_bytes=guild_upload_limit(interaction.guild),
        )

    @app_commands.checks.cooldown(3, 30, key=lambda i: i.user.id)
    async def picture_menu(
        self, interaction: discord.Interaction, message: discord.Message
    ) -> None:
        attachment = first_attachment(message, is_text)
        text = await self.read_text(attachment) if attachment else ascii_text_in_message(message)
        if text is None:
            raise UserFacingError("That message has no ASCII art (.txt or code block).")
        await interaction.response.defer(thinking=True)
        await self.send_picture(
            interaction.followup.send,
            text,
            attachment.filename if attachment else "ascii.txt",
            style="smooth",
            invert=False,
            max_bytes=guild_upload_limit(interaction.guild),
        )

    @app_commands.checks.cooldown(3, 30, key=lambda i: i.user.id)
    async def avatar_menu(
        self, interaction: discord.Interaction, user: discord.Member | discord.User
    ) -> None:
        await interaction.response.defer(thinking=True)
        data, filename = await avatar_bytes(user)
        await self.send_ascii(
            interaction.followup.send,
            data,
            filename,
            width=60,
            invert=False,
            max_bytes=guild_upload_limit(interaction.guild),
        )


async def setup(bot: GeorgeBot) -> None:
    await bot.add_cog(Ascii(bot))
