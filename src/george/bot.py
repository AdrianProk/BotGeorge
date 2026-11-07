"""The bot: wiring of config, storage, services and cogs."""

from __future__ import annotations

import contextlib
import logging
import shutil
import time

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

from george.config import Settings
from george.errors import UserFacingError, truncate
from george.services.reddit import RedditService
from george.services.youtube import YouTubeService
from george.storage.content_repo import ContentRepo, import_initial_content
from george.storage.db import Database

log = logging.getLogger(__name__)

EXTENSIONS = (
    "george.cogs.basic",
    "george.cogs.content",
    "george.cogs.meme",
    "george.cogs.qr",
    "george.cogs.mp3",
)

# Discord's default upload limit, used in DMs where there's no guild limit.
DEFAULT_UPLOAD_LIMIT = 10 * 1024 * 1024


def upload_limit(ctx: commands.Context) -> int:
    return ctx.guild.filesize_limit if ctx.guild else DEFAULT_UPLOAD_LIMIT


class GeorgeBot(commands.Bot):
    def __init__(self, settings: Settings) -> None:
        intents = discord.Intents.default()
        intents.message_content = True  # needed for the `$` prefix commands

        kwargs = {}
        if settings.owner_ids:
            kwargs["owner_ids"] = set(settings.owner_ids)

        super().__init__(
            command_prefix=commands.when_mentioned_or(settings.command_prefix),
            intents=intents,
            case_insensitive=True,  # `$Meme`, `$meme` and `$MEME` all work
            help_command=None,  # replaced by our own hybrid `help`
            # Never let stored or user text ping @everyone, roles or users.
            allowed_mentions=discord.AllowedMentions.none(),
            activity=discord.Game(name=f"{settings.command_prefix}help"),
            **kwargs,
        )
        self.settings = settings
        self.db = Database(settings.db_path)
        self.content = ContentRepo(self.db)
        self.youtube = YouTubeService(
            max_duration_s=settings.mp3_max_duration_s,
            max_concurrent=settings.mp3_max_concurrent,
            ffmpeg_location=settings.ffmpeg_location,
        )
        self.http_session: aiohttp.ClientSession | None = None
        self.reddit: RedditService | None = None
        self.started_at = time.time()

    # -- lifecycle ---------------------------------------------------------------

    async def setup_hook(self) -> None:
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        await self.db.connect()
        await import_initial_content(self.content, self.settings.data_dir)

        self.http_session = aiohttp.ClientSession()
        self.reddit = RedditService(
            self.http_session,
            user_agent=self.settings.reddit_user_agent,
            client_id=self.settings.reddit_client_id,
            client_secret=self.settings.reddit_client_secret,
        )

        for ext in EXTENSIONS:
            if ext == "george.cogs.mp3" and not self.ffmpeg_available():
                log.error("ffmpeg not found: the mp3 command is disabled. Install ffmpeg.")
                continue
            await self.load_extension(ext)

        self.tree.error(self.on_app_command_error)

        if self.settings.sync_commands:
            await self._sync_commands()

        self.heartbeat.start()
        self.daily_backup.start()

    async def _sync_commands(self) -> None:
        if self.settings.guild_ids:
            for guild_id in self.settings.guild_ids:
                guild = discord.Object(id=guild_id)
                self.tree.copy_global_to(guild=guild)
                try:
                    synced = await self.tree.sync(guild=guild)
                    log.info("Synced %d slash commands to server %s", len(synced), guild_id)
                except discord.HTTPException as exc:
                    log.error("Could not sync slash commands to server %s: %s", guild_id, exc)
        else:
            synced = await self.tree.sync()
            log.info("Synced %d global slash commands", len(synced))

    async def close(self) -> None:
        log.info("Shutting down…")
        self.heartbeat.cancel()
        self.daily_backup.cancel()
        await self.youtube.drain(timeout_s=60)
        await super().close()
        if self.http_session is not None:
            await self.http_session.close()
        await self.db.close()

    def ffmpeg_available(self) -> bool:
        if self.settings.ffmpeg_location:
            return True
        return shutil.which("ffmpeg") is not None

    # -- background tasks ----------------------------------------------------------

    @tasks.loop(seconds=30)
    async def heartbeat(self) -> None:
        """Touch a file so a container health check can tell the bot is alive."""
        if self.is_ready() and not self.is_closed():
            self.settings.heartbeat_path.write_text(str(int(time.time())), encoding="utf-8")

    @tasks.loop(hours=24)
    async def daily_backup(self) -> None:
        try:
            path = await self.db.backup(
                self.settings.backup_dir, self.settings.backup_keep, min_age_s=20 * 3600
            )
            if path:
                log.info("Database backup written to %s", path)
        except Exception:
            log.exception("Database backup failed")

    # -- events --------------------------------------------------------------------

    async def on_ready(self) -> None:
        assert self.user is not None
        log.info(
            "Logged in as %s (id %s) in %d server(s)", self.user, self.user.id, len(self.guilds)
        )

    async def on_disconnect(self) -> None:
        log.warning("Disconnected from Discord")

    async def on_resumed(self) -> None:
        log.info("Connection to Discord resumed")

    # -- owner notifications ---------------------------------------------------------

    async def notify_owner(self, text: str) -> None:
        channel_id = self.settings.owner_log_channel_id
        if not channel_id:
            return
        channel = self.get_channel(channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            log.warning("OWNER_LOG_CHANNEL_ID %s is not a text channel I can see", channel_id)
            return
        try:
            await channel.send(truncate(text))
        except discord.HTTPException as exc:
            log.warning("Could not post to owner log channel: %s", exc)

    # -- error handling ----------------------------------------------------------------

    async def on_command_error(self, ctx: commands.Context, error: Exception) -> None:
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, commands.HybridCommandError):
            error = error.original
        if isinstance(error, commands.CommandInvokeError | app_commands.CommandInvokeError):
            error = error.original

        message: str | None
        if isinstance(error, UserFacingError):
            message = str(error)
            if error.notify_owner:
                await self.notify_owner(
                    f"⚠️ `{ctx.command}` failed for {ctx.author} in {ctx.guild or 'DMs'}: {error}"
                )
        elif isinstance(error, commands.CommandOnCooldown | app_commands.CommandOnCooldown):
            message = f"Slow down! Try again in {error.retry_after:.0f} s."
        elif isinstance(error, commands.MaxConcurrencyReached):
            message = "You already have one of those running. Wait until it's finished :)"
        elif isinstance(error, commands.MissingRequiredArgument):
            extras = ctx.command.extras if ctx.command else {}
            usage = (
                f"{ctx.clean_prefix}{ctx.command} {ctx.command.signature if ctx.command else ''}"
            )
            message = extras.get("missing_text") or (
                f"You forgot the `{error.param.name}`. Usage: `{usage.strip()}`"
            )
        elif isinstance(error, commands.BadArgument | commands.BadLiteralArgument):
            message = f"I didn't understand that: {error}"
        elif isinstance(error, commands.CheckFailure | app_commands.CheckFailure):
            message = str(error) or "You're not allowed to do that."
        else:
            log.error(
                "Unhandled error in command %s",
                ctx.command,
                exc_info=(type(error), error, error.__traceback__),
            )
            message = "Something went wrong :( The error was logged."
            await self.notify_owner(f"💥 Unhandled error in `{ctx.command}`: `{error!r}`")

        try:
            await ctx.send(truncate(message), ephemeral=True)
        except discord.HTTPException:
            log.warning("Could not send error message for %s", ctx.command)

    async def on_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        # Hybrid commands report through on_command_error; this only catches pure app commands.
        log.error("App command error", exc_info=(type(error), error, error.__traceback__))
        send = (
            interaction.followup.send
            if interaction.response.is_done()
            else interaction.response.send_message
        )
        with contextlib.suppress(discord.HTTPException):
            await send("Something went wrong :(", ephemeral=True)
