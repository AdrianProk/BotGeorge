"""Random memes from Reddit."""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from george.bot import upload_limit
from george.errors import truncate

if TYPE_CHECKING:
    from george.bot import GeorgeBot


class Meme(commands.Cog):
    def __init__(self, bot: GeorgeBot) -> None:
        self.bot = bot

    @commands.hybrid_command(name="meme", description="I show you a random meme I stole off Reddit")
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def meme(self, ctx: commands.Context) -> None:
        assert self.bot.reddit is not None
        channel = ctx.channel
        allow_nsfw = isinstance(channel, discord.TextChannel | discord.Thread) and channel.is_nsfw()
        max_bytes = min(upload_limit(ctx), self.bot.settings.meme_max_bytes)

        async with ctx.typing():
            meme = await self.bot.reddit.random_meme(
                self.bot.settings.subreddits, allow_nsfw=allow_nsfw, max_bytes=max_bytes
            )
        await ctx.send(
            truncate(f"Here is a meme, just for you :) I got it from r/{meme.subreddit}"),
            file=discord.File(io.BytesIO(meme.data), filename=meme.filename),
        )


async def setup(bot: GeorgeBot) -> None:
    await bot.add_cog(Meme(bot))
