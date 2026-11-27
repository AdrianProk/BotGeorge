"""YouTube → MP3."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

import discord
from discord import app_commands
from discord.ext import commands

from george.bot import guild_upload_limit, upload_limit
from george.cogs.sources import find_youtube_url, replied_message, youtube_url_in_message
from george.errors import UserFacingError, truncate
from george.services.youtube import format_duration

Send = Callable[..., Awaitable[Any]]

if TYPE_CHECKING:
    from george.bot import GeorgeBot


MISSING_LINK = "Put a YouTube link behind the command, or reply to a message that has one."


class Mp3(commands.Cog):
    def __init__(self, bot: GeorgeBot) -> None:
        self.bot = bot
        self._busy_users: set[int] = set()  # one conversion per person at a time
        self.menu = app_commands.ContextMenu(name="Convert to MP3", callback=self.mp3_menu)

    async def cog_load(self) -> None:
        self.bot.tree.add_command(self.menu)

    async def cog_unload(self) -> None:
        self.bot.tree.remove_command(self.menu.name, type=self.menu.type)

    async def convert_and_send(self, send: Send, user_id: int, url: str, max_bytes: int) -> None:
        if user_id in self._busy_users:
            raise UserFacingError(
                "You already have a conversion running. Wait until it's finished :)"
            )
        self._busy_users.add(user_id)
        try:
            youtube = self.bot.youtube
            await send(
                "I'm busy with other songs, you're in the queue. Give me a moment…"
                if youtube.busy
                else "Alright, give me a moment……"
            )

            async def on_update(version: str) -> None:
                await send(
                    f"YouTube changed something, so I updated my downloader to {version}. Trying again…"
                )
                await self.bot.notify_owner(
                    f"⬆️ yt-dlp updated after a failed download: now {version}"
                )

            async with youtube.convert(url, max_bytes=max_bytes, on_update=on_update) as result:
                await send(
                    truncate(
                        f"Here is your Mp3 :) **{discord.utils.escape_markdown(result.title)}** "
                        f"({format_duration(result.duration_s)}, {result.bitrate_kbps} kbps)"
                    ),
                    file=discord.File(result.path, filename=result.filename),
                )
        finally:
            self._busy_users.discard(user_id)

    @commands.hybrid_command(
        name="mp3",
        description="Send me a YouTube link (or reply to one) and I'll get you the MP3",
    )
    @app_commands.describe(link="The YouTube link")
    @commands.cooldown(2, 60, commands.BucketType.user)
    async def mp3(self, ctx: commands.Context, link: str | None = None) -> None:
        url = find_youtube_url(link) if link else None
        if url is None and link is None:
            replied = await replied_message(ctx)
            url = youtube_url_in_message(replied) if replied else None
        if url is None:
            raise UserFacingError("That's not a YouTube video link." if link else MISSING_LINK)
        async with ctx.typing():
            await self.convert_and_send(ctx.send, ctx.author.id, url, upload_limit(ctx))

    @app_commands.checks.cooldown(2, 60, key=lambda i: i.user.id)
    async def mp3_menu(self, interaction: discord.Interaction, message: discord.Message) -> None:
        url = youtube_url_in_message(message)
        if url is None:
            raise UserFacingError("That message has no YouTube video link.")
        await interaction.response.defer(thinking=True)
        await self.convert_and_send(
            interaction.followup.send,
            interaction.user.id,
            url,
            guild_upload_limit(interaction.guild),
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
