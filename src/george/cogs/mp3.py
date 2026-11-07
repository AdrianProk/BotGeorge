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

        async def on_update(version: str) -> None:
            await ctx.send(
                f"YouTube changed something, so I updated my downloader to {version}. Trying again…"
            )
            await self.bot.notify_owner(f"⬆️ yt-dlp updated after a failed download: now {version}")

        async with (
            ctx.typing(),
            youtube.convert(url, max_bytes=upload_limit(ctx), on_update=on_update) as result,
        ):
            await ctx.send(
                truncate(
                    f"Here is your Mp3 :) **{discord.utils.escape_markdown(result.title)}** "
                    f"({format_duration(result.duration_s)}, {result.bitrate_kbps} kbps)"
                ),
                file=discord.File(result.path, filename=result.filename),
            )

    @commands.hybrid_command(
        name="ytdlp", description="Owner only: check for a yt-dlp update right now"
    )
    @commands.is_owner()
    async def ytdlp(self, ctx: commands.Context) -> None:
        updater = self.bot.ytdlp
        async with ctx.typing():
            before = updater.active_version
            new = await updater.update_if_available()
        if new:
            text = f"Updated yt-dlp {before} → {new}. The next download uses it."
        elif updater.last_error:
            text = f"Update check failed: {updater.last_error}. Still using {before}."
        elif not updater.enabled:
            text = f"Auto-update is turned off (YTDLP_AUTO_UPDATE). Using {before}."
        else:
            text = f"yt-dlp {before} ({updater.active_source}) is the newest {updater.channel} version."
        await ctx.send(truncate(text), ephemeral=True)


async def setup(bot: GeorgeBot) -> None:
    await bot.add_cog(Mp3(bot))
