"""QR code creation."""

from __future__ import annotations

import asyncio
import io
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from george.cogs.sources import qr_text_in_message, replied_message
from george.errors import UserFacingError
from george.services.qr import make_qr_png

if TYPE_CHECKING:
    from george.bot import GeorgeBot

MISSING_TEXT = "Put some text behind the command, or reply to a message to turn it into a QR code."


async def qr_file(text: str) -> discord.File:
    png = await asyncio.to_thread(make_qr_png, text)
    return discord.File(io.BytesIO(png), "qr.png")


class QR(commands.Cog):
    def __init__(self, bot: GeorgeBot) -> None:
        self.bot = bot
        self.menu = app_commands.ContextMenu(name="Make QR code", callback=self.qr_menu)

    async def cog_load(self) -> None:
        self.bot.tree.add_command(self.menu)

    async def cog_unload(self) -> None:
        self.bot.tree.remove_command(self.menu.name, type=self.menu.type)

    @commands.hybrid_command(
        name="qr",
        aliases=["createqr"],
        description="I make a QR code from your text or link (or the message you reply to)",
    )
    @app_commands.describe(text="Text or link for the QR code")
    @commands.cooldown(3, 15, commands.BucketType.user)
    async def qr(self, ctx: commands.Context, *, text: str | None = None) -> None:
        if not text or not text.strip():
            replied = await replied_message(ctx)
            text = qr_text_in_message(replied) if replied else None
        if not text:
            raise UserFacingError(MISSING_TEXT)
        await ctx.send("Here is your QR code :)", file=await qr_file(text))

    @app_commands.checks.cooldown(3, 15, key=lambda i: i.user.id)
    async def qr_menu(self, interaction: discord.Interaction, message: discord.Message) -> None:
        text = qr_text_in_message(message)
        if not text:
            raise UserFacingError("There's nothing in that message I could put into a QR code.")
        file = await qr_file(text)
        await interaction.response.send_message("Here is your QR code :)", file=file)


async def setup(bot: GeorgeBot) -> None:
    await bot.add_cog(QR(bot))
