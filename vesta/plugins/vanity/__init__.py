from contextlib import suppress
from typing import Annotated, cast

from discord import (
    CustomActivity,
    HTTPException,
    Member,
    Message,
    Role,
    Status,
    TextChannel,
    Embed
)
from discord.ext.commands import Cog, check, group, has_permissions
from discord.utils import find

from vesta.framework import Context, Vesta
from vesta.framework.tools.conversion import StrictRole
from vesta.framework.tools.formatter import vowel, codeblock
from vesta.framework.script import Script


class Vanity(Cog):
    def __init__(self, bot: Vesta):
        self.bot = bot


    def get_status(self, member: Member) -> str:
        """
        Return the member's custom status.
        """

        return str(
            find(
                lambda activity: isinstance(activity, CustomActivity),
                member.activities,
            )
        ).lower()
    
    @group(
        aliases=["vr"],
        invoke_without_command=True,
    )
    @has_permissions(manage_roles=True)
    async def vanity(self, ctx: Context) -> Message:
        """
        Award members for advertising your server.
        """
        return await ctx.send_help(ctx.command)

    @vanity.group(
        name="channel",
        aliases=["logs"],
        invoke_without_command=True,
        example="#vanity",
    )
    @has_permissions(manage_roles=True)
    async def vanity_channel(
        self,
        ctx: Context,
        *,
        channel: TextChannel,
    ) -> Message:
        """
        Set the channel to send award logs.
        """
        if not ctx.guild.vanity_url_code:
            return await ctx.embed(
                message="Your server must be **level 3** boosted or have a vanity set to use this feature!",
                message_type="warned"
            )

        await self.bot.pool.execute(
            """
            INSERT INTO vanity (guild_id, channel_id)
            VALUES ($1, $2)
            ON CONFLICT (guild_id)
            DO UPDATE SET channel_id = EXCLUDED.channel_id
            """,
            ctx.guild.id,
            channel.id,
        )
        return await ctx.embed(
            message=f"Now sending award logs to {channel.mention}",
            message_type="approved"
        )

    @vanity_channel.command(
        name="remove",
        aliases=["delete", "del", "rm"],
        example="#vanity",
    )
    @has_permissions(manage_roles=True)
    async def vanity_channel_remove(self, ctx: Context) -> Message:
        """
        Remove award logs channel.
        """
        if not ctx.guild.vanity_url_code:
            return await ctx.embed(
                message="Your server must be **level 3** boosted or have a vanity set to use this feature!",
                message_type="warned"
            )

        await self.bot.pool.execute(
            """
            UPDATE vanity
            SET channel_id = NULL
            WHERE guild_id = $1
            """,
            ctx.guild.id,
        )
        return await ctx.embed(
            message="No longer sending award logs",
            message_type="approved"
        )

    @vanity.command(
        name="message",
        aliases=["msg", "template"],
        example="Thank you {user.mention} for advertising our server!",
    )
    @has_permissions(manage_roles=True)
    async def vanity_message(
        self,
        ctx: Context,
        *,
        script: Script,
    ) -> Message:
        """
        Set the award message.

        The following variables are available:
        > `{role}`: The award role.
        > `{vanity}`: The vanity code.
        """
        if not ctx.guild.vanity_url_code:
            return await ctx.embed(
                message="Your server must be **level 3** boosted to use this feature!",
                message_type="warned"
            )

        existing = await self.bot.pool.fetchrow(
            """
            SELECT * FROM vanity 
            WHERE guild_id = $1
            """,
            ctx.guild.id
        )

        if not existing:
            await self.bot.pool.execute(
                """
                INSERT INTO vanity (guild_id, template)
                VALUES ($1, $2)
                """,
                ctx.guild.id,
                script.template
            )
        else:
            await self.bot.pool.execute(
                """
                UPDATE vanity 
                SET template = $1
                WHERE guild_id = $2
                """,
                script.template,
                ctx.guild.id,
            )

        return await ctx.embed(
            message=f"Successfully set {vowel(script.format)} award message",
            message_type="approved"
        )
    
    @vanity.command(
        name="view",
        aliases=["show"],
    )
    @has_permissions(manage_roles=True)
    async def vanity_view(self, ctx: Context) -> Message:
        """
        Show vanity message and award role.
        """
        if not ctx.guild.vanity_url_code:
            return await ctx.embed(
                message="Your server must be **level 3** boosted to use this feature!",
                message_type="warned"
            )

        record = await self.bot.pool.fetchrow(
            """
            SELECT * FROM vanity
            WHERE guild_id = $1
            """,
            ctx.guild.id,
        )
        if not record:
            return await ctx.embed(
                message="No vanity settings found!",
                message_type="warned"
            )

        role = ctx.guild.get_role(record["role_id"])
        channel = ctx.guild.get_channel(record["channel_id"])
        template = record["template"]

        if template:
            script = Script(template, [ctx.guild, ctx.author, channel])
            await ctx.send(codeblock(script))

        if template:
            result = await script.convert(ctx, template)
            await result.send(ctx.channel)

        embed=Embed(
                title="Vanity Settings",
                description=(
                    f"**Role:** {role.mention if role else 'None'}\n"
                    f"**Channel:** {channel.mention if channel else 'None'}\n"
                    f"**Message:** {template or 'None'}"
                ),
            )

        return await ctx.send(embed=embed)

    @vanity.command(
        name="disable",
        aliases=["reset"],
    )
    @has_permissions(manage_roles=True)
    async def vanity_disable(self, ctx: Context) -> Message:
        """
        Reset & disable the award system.
        """
        if not ctx.guild.vanity_url_code:
            return await ctx.embed(
                message="Your server must be **level 3** boosted or have a vanity set to use this feature!",
                message_type="warned"
            )

        await ctx.prompt("Are you sure you completely reset the award system?")

        await self.bot.pool.execute(
            """
            DELETE FROM vanity
            WHERE guild_id = $1
            """,
            ctx.guild.id,
        )
        return await ctx.embed(
            message="No longer awarding members for advertising your server",
            message_type="approved"
        )
    
    @Cog.listener("on_presence_update")
    async def vanity_listener(self, before: Member, member: Member):
        """
        Award the member if they have the vanity URL in their status.
        If the member has the role without the vanity URL in their status,
        the role will be automatically removed.
        """
        guild = member.guild
        if not (vanity := guild.vanity_url_code):
            return

        record = await self.bot.pool.fetchrow(
            """
            SELECT * FROM vanity
            WHERE guild_id = $1
            """,
            guild.id,
        )
        if not record:
            return

        role = guild.get_role(record["role_id"])
        if not role or not role.is_assignable():
            return

        before_status = self.get_status(before)
        status = self.get_status(member)
        if before_status == status:
            return

        with suppress(HTTPException):
            if vanity not in status and role in member.roles:
                await member.remove_roles(
                    role,
                    reason="Vanity no longer in status",
                )

            elif vanity in status and role not in member.roles:
                await member.add_roles(
                    role,
                    reason="Vanity added to status",
                )

                if (
                    before.status != Status.offline
                    and before.status == member.status
                    and (
                        channel := cast(
                            TextChannel, guild.get_channel(record["channel_id"])
                        )
                    )
                    and not await self.bot.redis.ratelimited(
                         f"vanity:{guild.id}:{member.id}",
                         limit=1,
                         timespan=1800,
                     )
                ):
                  
                    template = record["template"]
                    default_template = (
                        "{title: vanity set}"
                        "{description: thank you {user.mention}}"
                        "{footer: put /{vanity} in your status for the role.}"
                    )
                    
                    script = Script(
                        (template or default_template).replace("{vanity}", vanity),
                        [guild, member, channel],
                    )

                    try:
                        await script.send(channel)
                    
                    except HTTPException as e:
                        return await self.bot.pool.execute(
                            """
                            UPDATE vanity
                            SET template = NULL
                            WHERE guild_id = $1
                            """,
                            guild.id,
                        )