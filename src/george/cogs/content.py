"""User-taught content: prompts, swears, compliments, random lines.

The lists are shared between all servers the bot is in.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from george.errors import UserFacingError, truncate
from george.storage.content_repo import (
    Category,
    DuplicateEntryError,
    InvalidEntryError,
)

if TYPE_CHECKING:
    from george.bot import GeorgeBot

PAGE_SIZE = 15

ADD_REPLIES: dict[str, tuple[str, str]] = {
    # category: (success reply, reply when text is missing)
    "prompt": (
        "Your prompt has been saved :D",
        "What's your prompt? It can't be empty. Type it after the command, all in the same line :)",
    ),
    "swear": (
        "Now I learned something bad >:D",
        "That's it?!?! You have to say something if you want me to learn something bad!",
    ),
    "compliment": (
        "Now I learned something nice :D",
        "You have to say something to teach me something nice. Write your compliment after the command.",
    ),
    "random": (
        "Now I learned something random :D",
        "You have to say something to teach me something. Write something after the command.",
    ),
}


class Content(commands.Cog):
    def __init__(self, bot: GeorgeBot) -> None:
        self.bot = bot

    # -- reading ---------------------------------------------------------------------

    async def _send_random(self, ctx: commands.Context, category: str, add_cmd: str) -> None:
        text = await self.bot.content.random(category)
        if text is None:
            prefix = self.bot.settings.command_prefix
            await ctx.send(f"I don't know any yet. Teach me with `{prefix}{add_cmd} <text>`!")
            return
        await ctx.send(truncate(text))

    @commands.hybrid_command(name="prompt", description="I give you an art prompt")
    async def prompt(self, ctx: commands.Context) -> None:
        await self._send_random(ctx, "prompt", "addprompt")

    @commands.hybrid_command(name="fuckyou", description="You get what you deserve")
    async def fuckyou(self, ctx: commands.Context) -> None:
        await self._send_random(ctx, "swear", "addswear")

    @commands.hybrid_command(name="compliment", description="I give you a compliment")
    async def compliment(self, ctx: commands.Context) -> None:
        await self._send_random(ctx, "compliment", "addcompliment")

    @commands.hybrid_command(name="random", description="I say something random")
    async def random_(self, ctx: commands.Context) -> None:
        await self._send_random(ctx, "random", "addrandom")

    # -- adding ----------------------------------------------------------------------

    async def _add(self, ctx: commands.Context, category: str, text: str) -> None:
        success, _ = ADD_REPLIES[category]
        try:
            entry = await self.bot.content.add(
                category,
                text,
                author_id=ctx.author.id,
                origin_guild_id=ctx.guild.id if ctx.guild else None,
            )
        except DuplicateEntryError:
            raise UserFacingError("I already know that one :)") from None
        except InvalidEntryError as exc:
            raise UserFacingError(str(exc)) from None

        await ctx.send(success)
        await self.bot.notify_owner(
            f"📝 New {category} #{entry.id} by {ctx.author} ({ctx.author.id}) "
            f"from {ctx.guild or 'DMs'}: {entry.text}"
        )

    @commands.hybrid_command(
        name="addprompt",
        description="Teach me an art prompt",
        extras={"missing_text": ADD_REPLIES["prompt"][1]},
    )
    @commands.cooldown(3, 30, commands.BucketType.user)
    async def addprompt(self, ctx: commands.Context, *, text: str) -> None:
        await self._add(ctx, "prompt", text)

    @commands.hybrid_command(
        name="addswear",
        description="Teach me a swear",
        extras={"missing_text": ADD_REPLIES["swear"][1]},
    )
    @commands.cooldown(3, 30, commands.BucketType.user)
    async def addswear(self, ctx: commands.Context, *, text: str) -> None:
        await self._add(ctx, "swear", text)

    @commands.hybrid_command(
        name="addcompliment",
        description="Teach me a compliment",
        extras={"missing_text": ADD_REPLIES["compliment"][1]},
    )
    @commands.cooldown(3, 30, commands.BucketType.user)
    async def addcompliment(self, ctx: commands.Context, *, text: str) -> None:
        await self._add(ctx, "compliment", text)

    @commands.hybrid_command(
        name="addrandom",
        description="Teach me something random",
        extras={"missing_text": ADD_REPLIES["random"][1]},
    )
    @commands.cooldown(3, 30, commands.BucketType.user)
    async def addrandom(self, ctx: commands.Context, *, text: str) -> None:
        await self._add(ctx, "random", text)

    # -- moderation ------------------------------------------------------------------

    @commands.hybrid_group(name="content", description="Look at or clean up what I've learned")
    async def content(self, ctx: commands.Context) -> None:
        prefix = self.bot.settings.command_prefix
        await ctx.send(
            f"Use `{prefix}content list <category> [page]` or `{prefix}content remove <id>`.",
            ephemeral=True,
        )

    @content.command(name="list", description="List entries of a category")
    async def content_list(self, ctx: commands.Context, category: Category, page: int = 1) -> None:
        total = await self.bot.content.count(category)
        pages = max(1, -(-total // PAGE_SIZE))
        page = min(max(page, 1), pages)
        entries = await self.bot.content.list(
            category, limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE
        )
        if not entries:
            await ctx.send(f"There are no {category} entries yet.", ephemeral=True)
            return
        lines = []
        for e in entries:
            who = f"<@{e.author_id}>" if e.author_id else "seed"
            text = e.text if len(e.text) <= 80 else e.text[:79] + "…"
            lines.append(f"`#{e.id}` {discord.utils.escape_markdown(text)} — {who}")
        embed = discord.Embed(
            title=f"{category} ({total})",
            description="\n".join(lines),
            colour=discord.Colour.dark_grey(),
        )
        embed.set_footer(text=f"Page {page}/{pages}")
        await ctx.send(embed=embed, ephemeral=True)

    @content.command(name="remove", description="Remove an entry by its #id")
    async def content_remove(self, ctx: commands.Context, entry_id: int) -> None:
        entry = await self.bot.content.get(entry_id)
        if entry is None:
            raise UserFacingError(f"There is no entry #{entry_id}.")

        allowed = await self.bot.is_owner(ctx.author) or entry.author_id == ctx.author.id
        if (
            not allowed
            and ctx.guild is not None
            and entry.origin_guild_id == ctx.guild.id
            and isinstance(ctx.author, discord.Member)
            and ctx.author.guild_permissions.manage_messages
        ):
            allowed = True
        if not allowed:
            raise UserFacingError(
                "You can only remove entries you added yourself, or (as a moderator) "
                "entries that were added from this server. The list is shared between servers."
            )

        await self.bot.content.delete(entry_id)
        await ctx.send(f"Removed #{entry_id}: {truncate(entry.text, 200)}", ephemeral=True)
        await self.bot.notify_owner(
            f"🗑️ {ctx.author} ({ctx.author.id}) removed {entry.category} #{entry.id}: {entry.text}"
        )


async def setup(bot: GeorgeBot) -> None:
    await bot.add_cog(Content(bot))
