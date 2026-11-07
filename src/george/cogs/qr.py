"""QR code creation."""

from __future__ import annotations

import asyncio
import io
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from george.services.qr import make_qr_png

if TYPE_CHECKING:
    from george.bot import GeorgeBot


class QR(commands.Cog):
    def __init__(self, bot: GeorgeBot) -> None:
        self.bot = bot

    @commands.hybrid_command(
        name="qr",
        aliases=["createqr"],
        description="I make a QR code from your text or link",
        extras={
            "missing_text": "Please put something behind the command, or I can't put anything in it."
        },
    )
    @commands.cooldown(3, 15, commands.BucketType.user)
    async def qr(self, ctx: commands.Context, *, text: str) -> None:
        png = await asyncio.to_thread(make_qr_png, text)
        await ctx.send("Here is your QR code :)", file=discord.File(io.BytesIO(png), "qr.png"))


async def setup(bot: GeorgeBot) -> None:
    await bot.add_cog(QR(bot))
