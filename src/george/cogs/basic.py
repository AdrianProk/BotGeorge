"""hello, name, help, version."""

from __future__ import annotations

import asyncio
import platform
import shutil
import time
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from george import __version__

if TYPE_CHECKING:
    from george.bot import GeorgeBot


async def _tool_version(binary: str, *args: str) -> str:
    path = shutil.which(binary)
    if not path:
        return "not installed"
    try:
        proc = await asyncio.create_subprocess_exec(
            path, *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
    except (OSError, TimeoutError):
        return "unknown"
    first_line = out.decode(errors="replace").splitlines()[0] if out else "unknown"
    return first_line[:80]


class Basic(commands.Cog):
    def __init__(self, bot: GeorgeBot) -> None:
        self.bot = bot

    @commands.hybrid_command(name="hello", description="I say hello to you")
    async def hello(self, ctx: commands.Context) -> None:
        await ctx.send("Hello!")

    @commands.hybrid_command(name="name", description="I introduce myself")
    async def name_(self, ctx: commands.Context) -> None:
        await ctx.send("My name is George, the creepy Gargoyle :D")

    @commands.hybrid_command(name="help", description="Shows all my commands")
    async def help_(self, ctx: commands.Context) -> None:
        prefix = self.bot.settings.command_prefix
        embed = discord.Embed(
            title="My commands",
            description=f"Use them with `{prefix}` (e.g. `{prefix}meme`) or as slash commands (`/meme`).",
            colour=discord.Colour.dark_grey(),
        )
        for cog_name, cog in sorted(self.bot.cogs.items()):
            lines = []
            for command in sorted(cog.get_commands(), key=lambda c: c.name):
                if command.hidden:
                    continue
                usage = f"{prefix}{command.name} {command.signature}".strip()
                lines.append(f"`{usage}` – {command.description or command.help or ''}")
                if isinstance(command, commands.Group):
                    for sub in sorted(command.commands, key=lambda c: c.name):
                        sub_usage = f"{prefix}{command.name} {sub.name} {sub.signature}".strip()
                        lines.append(f"`{sub_usage}` – {sub.description or sub.help or ''}")
            if lines:
                embed.add_field(name=cog_name, value="\n".join(lines)[:1024], inline=False)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="version", description="Shows my version and my tools' versions")
    async def version(self, ctx: commands.Context) -> None:
        ffmpeg, deno = await asyncio.gather(
            _tool_version("ffmpeg", "-version"), _tool_version("deno", "--version")
        )
        uptime_min = int((time.time() - self.bot.started_at) // 60)
        await ctx.send(
            "```\n"
            f"George   {__version__}\n"
            f"Python   {platform.python_version()}\n"
            f"discord  {discord.__version__}\n"
            f"yt-dlp   {self.bot.ytdlp.active_version} ({self.bot.ytdlp.active_source})\n"
            f"ffmpeg   {ffmpeg}\n"
            f"deno     {deno}\n"
            f"uptime   {uptime_min // 60} h {uptime_min % 60} min\n"
            "```"
        )


async def setup(bot: GeorgeBot) -> None:
    await bot.add_cog(Basic(bot))
