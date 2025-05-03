from discord import Message, Embed
from discord.ext.commands import group, has_permissions
from discord.ext.commands import Cog, BadArgument

from vesta.framework import Vesta, Context
from vesta.shared.config import Configuration


class Prefix(Cog):
    """
    Control the server prefix.
    """
    def __init__(self, bot: Vesta):
        self.bot = bot

    @group(invoke_without_command=True)
    async def prefix(self, ctx: Context) -> Message:
        """
        View the current server prefixes.
        """
        guild_prefix = await self.bot.pool.fetchval(
            """
            SELECT prefix 
            FROM prefix 
            WHERE guild_id = $1
            """,
            ctx.guild.id,
        )

        prefixes = []

        if guild_prefix:
            prefixes.append(f"`{guild_prefix}` [Server]")

        if not guild_prefix:
            prefixes.append(
                f"`{Configuration().defaults.prefix}` [Default]"
            )

        embed = Embed(
            description="\n".join(prefixes),
        )

        embed.set_author(
            name=f"Current Prefixes",
            icon_url=ctx.author.display_avatar.url,
        )
        await ctx.send(embed=embed)

    @prefix.command(name="set")
    @has_permissions(manage_guild=True)
    async def prefix_set(
        self, ctx: Context, prefix: str
    ) -> Message:
        """
        Set the server prefix.
        """
        if len(prefix) > 7:
            raise BadArgument("Prefix is too long!")

        if not prefix:
            return await ctx.embed(
                "Prefix is too short!", "warned"
            )

        await self.bot.update_guild_prefix(
            ctx.guild.id, prefix
        )
        return await ctx.embed(
            f"Guild prefix changed to `{prefix}`",
            "approved",
        )

async def setup(bot: "Vesta") -> None:
    await bot.add_cog(Prefix(bot))
