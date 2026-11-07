"""YouTube → MP3."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from george.bot import upload_limit
from george.errors import UserFacingError, truncate
from george.services.youtube import format_duration, normalize_youtube_url

if TYPE_CHECKING:
    from george.bot import GeorgeBot


class Mp3(commands.Cog):
    def __init__(self, bot: GeorgeBot) -> None:
        self.bot = bot

    @commands.hybrid_command(
        name="mp3",
        description="Send me a YouTube link and I'll get you the MP3",
        extras={"missing_text": "Please put a valid YouTube link behind the command."},
    )
    @commands.cooldown(2, 60, commands.BucketType.user)
    @commands.max_concurrency(1, commands.BucketType.user, wait=False)
    async def mp3(self, ctx: commands.Context, link: str) -> None:
        url = normalize_youtube_url(link)
        if url is None:
            raise UserFacingError("Please put a valid YouTube link behind the command.")

        youtube = self.bot.youtube
        queued = youtube.busy
        await ctx.send(
            "I'm busy with other songs, you're in the queue. Give me a moment…"
            if queued
            else "Alright, give me a moment……"
        )

        async with ctx.typing(), youtube.convert(url, max_bytes=upload_limit(ctx)) as result:
            await ctx.send(
                truncate(
                    f"Here is your Mp3 :) **{discord.utils.escape_markdown(result.title)}** "
                    f"({format_duration(result.duration_s)}, {result.bitrate_kbps} kbps)"
                ),
                file=discord.File(result.path, filename=result.filename),
            )


async def setup(bot: GeorgeBot) -> None:
    await bot.add_cog(Mp3(bot))
