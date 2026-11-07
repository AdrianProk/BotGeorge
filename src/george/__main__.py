"""Entry point: `python -m george` or the `george` command."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import shutil
import signal
import sys

import aiohttp
import discord

from george.bot import GeorgeBot
from george.config import ConfigError, Settings, load_settings
from george.logging_setup import setup_logging

log = logging.getLogger("george")


def _check_tools(settings: Settings) -> None:
    if not settings.ffmpeg_location and shutil.which("ffmpeg") is None:
        log.error(
            "ffmpeg is not installed, so the mp3 command will be disabled. Install it with "
            "`winget install ffmpeg` (Windows), `brew install ffmpeg` (macOS) or "
            "`sudo apt install ffmpeg` (Debian/Ubuntu), or use the Docker image."
        )
    if shutil.which("deno") is None:
        log.warning(
            "Deno is not installed. yt-dlp needs a JavaScript runtime for YouTube, so mp3 "
            "downloads may fail. Install it from https://deno.com or use the Docker image."
        )


async def _run_bot(settings: Settings) -> None:
    bot = GeorgeBot(settings)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        # Not supported on Windows; Ctrl+C still works there via KeyboardInterrupt.
        with contextlib.suppress(NotImplementedError, RuntimeError):
            loop.add_signal_handler(sig, stop.set)

    async with bot:
        runner = asyncio.create_task(bot.start(settings.discord_token))
        waiter = asyncio.create_task(stop.wait())
        done, _ = await asyncio.wait({runner, waiter}, return_when=asyncio.FIRST_COMPLETED)
        if runner in done:
            waiter.cancel()
            runner.result()  # re-raise login errors etc.
            return
        log.info("Stop signal received")
        await bot.close()
        await runner


def run() -> None:
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        sys.exit(2)

    setup_logging(settings)
    _check_tools(settings)
    log.info("Data directory: %s", settings.data_dir)

    try:
        asyncio.run(_run_bot(settings))
    except discord.LoginFailure:
        log.error("Discord rejected the token. Check DISCORD_TOKEN in your .env file.")
        sys.exit(1)
    except discord.PrivilegedIntentsRequired:
        log.error(
            "The Message Content intent is not enabled. Turn it on in the Discord Developer "
            "Portal → your app → Bot → Privileged Gateway Intents."
        )
        sys.exit(1)
    except (aiohttp.ClientConnectionError, OSError) as exc:
        log.error("Can't reach Discord (%s). Check the internet connection.", exc)
        sys.exit(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()
