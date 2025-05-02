import datetime
import logging

from vesta.framework import Vesta
from vesta.shared.config import LoggingTypes

from contextlib import suppress

from discord import (
    HTTPException,
    Interaction,
    ButtonStyle,
    Guild,
    Embed,
    User,
)
from discord.ui import View, Button, button
from discord.ext.commands import (
    Converter,
    BadArgument,
    Context,
)

log = logging.getLogger("vesta/ownerlogs")


class OwnerID(View):
    """
    View for Owner ID confirmation with multiple buttons.
    """

    def __init__(self, response_messages: dict):
        super().__init__(timeout=None)
        self.response_messages = response_messages
        self.value = None

    @button(label="Owner ID", style=ButtonStyle.grey)
    async def ownerid(
        self, interaction: Interaction, button: Button
    ):
        """
        Retrieve the owner ID of the guild and send it as a response.
        """
        await interaction.response.send_message(
            self.response_messages.get(
                "owner-id", "No response set"
            ),
            ephemeral=True,
        )

    @button(label="Guild Invite", style=ButtonStyle.grey)
    async def invite(
        self, interaction: Interaction, button: Button
    ):
        """
        Create an invite link for the guild and send it as a response.
        """
        await interaction.response.send_message(
            self.response_messages.get(
                "guild-invite", "No response set"
            ),
            ephemeral=True,
        )


class OwnerLogs:
    """
    Log guild blacklists and unblacklists as well as user blacklists and unblacklists.
    Log when a guild adds and removes the bot.
    """

    def __init__(self, bot: Vesta):
        self.bot = bot

    async def guild_logger(self, guild: Guild, type: str):
        """
        Log when a guild adds or removes the bot.
        """
        if type == "joined":
            channel = self.bot.get_channel(
                LoggingTypes().guild_joined
            )

        elif type == "left":
            channel = self.bot.get_channel(
                LoggingTypes().guild_left
            )

        embed = Embed(
            timestamp=datetime.datetime.now(),
            title=f"{self.bot.user.name.capitalize()} has **{type}** a guild.",
        )

        icon = (
            f"[icon]({guild.icon.url})"
            if guild.icon
            else "N/A"
        )
        splash = (
            f"[splash]({guild.splash.url})"
            if guild.splash
            else "N/A"
        )
        banner = (
            f"[banner]({guild.banner.url})"
            if guild.banner
            else "N/A"
        )

        bot_count = (
            len([m for m in guild.members if m.bot])
            if hasattr(guild, "members")
            else 0
        )
        total_members = (
            guild.member_count
            if hasattr(guild, "member_count")
            else 0
        )
        user_count = (
            total_members - bot_count
            if total_members
            else 0
        )

        stats = {
            "user_count": user_count,
            "user_percentage": (
                (user_count / total_members * 100)
                if total_members
                else 0
            ),
            "bot_count": bot_count,
            "bot_percentage": (
                bot_count / total_members * 100
            )
            if total_members
            else 0,
        }

        fields = {
            "Owner": (
                f"{guild.owner.mention}\n{guild.owner.id}"
                if guild.owner
                else "Unknown Owner"
            ),
            "Members": (
                f">>> **Users:** ({stats['user_count']} ({stats['user_percentage']:.2f}%)\n"
                f"**Bots:** {stats['bot_count']} ({stats['bot_percentage']:.2f}%)\n"
                f"**Total:** {total_members if total_members else 'Unknown'}"
            ),
            "Information": (
                f">>> **Verification:** {guild.verification_level}\n"
                f"**Boosts:** {guild.premium_subscription_count}\n"
                f"**Level:** {guild.premium_tier}/3\n"
                f"**Large:** {'yes' if total_members and total_members > 2500 else 'no'}"
            ),
            "Design": f"{icon}\n{splash}\n{banner}",
            f"Channels ({len(guild.channels)}):": (
                f">>> **Text:** {len([channel for channel in guild.channels if channel.type.name == 'text'])}\n"
                f"**Voice:** {len([channel for channel in guild.channels if channel.type.name == 'voice'])}\n"
                f"**Categories:** {len([channel for channel in guild.channels if channel.type.name == 'category'])}"
            ),
            "Counts": (
                f">>> **Roles:** {len(guild.roles)}/250\n"
                f"**Emojis:** {len(guild.emojis)}/{guild.emoji_limit * 2}\n"
                f"**Stickers:** {len(guild.stickers)}/{guild.sticker_limit}"
            ),
        }

        for name, value in fields.items():
            embed.add_field(name=name, value=value)

        embed.set_footer(text=f"Guild ID: {guild.id}")

        if guild.banner:
            embed.set_image(url={guild.banner.url})

        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        view = None

        if guild.vanity_url:
            view = View()
            view.add_item(
                Button(
                    label="Invite",
                    url=f"https://discord.gg/{guild.vanity_url_code}",
                )
            )

        with suppress(Exception):
            return await channel.send(
                embed=embed, view=view, silent=True
            )

    async def guild_blacklist(
        self,
        ctx: Context,
        guild: int,
        type: str,
        reason: str,
    ) -> None:
        """
        Log when a guild is blacklisted or unblacklisted.
        """
        if type == "blacklisted":
            channel = self.bot.get_channel(
                LoggingTypes().guild_blacklist
            )

        elif type == "unblacklisted":
            channel = self.bot.get_channel(
                LoggingTypes().guild_unblacklist
            )

        embed = Embed(
            title=f"Guild {type.capitalize()}",
            timestamp=datetime.datetime.now(),
        )

        embed.add_field(
            name="Guild ID",
            value=f"``{guild}``",
            inline=False,
        )

        embed.add_field(
            name="Staff Mention",
            value=f"{ctx.author.mention}",
            inline=False,
        )

        embed.add_field(
            name="Staff ID",
            value=f"``{ctx.author.id}``",
            inline=False,
        )

        embed.add_field(
            name="Reason",
            value=reason,
            inline=False,
        )

        with suppress(HTTPException):
            return await channel.send(
                embed=embed, silent=True
            )

    async def user_blacklist(
        self,
        ctx: Context,
        user: User,
        type: str,
        reason: str,
    ) -> None:
        """
        Log when a user is blacklisted or unblacklisted.
        """
        if type == "blacklisted":
            channel = self.bot.get_channel(
                LoggingTypes().user_blacklist
            )

        elif type == "unblacklisted":
            channel = self.bot.get_channel(
                LoggingTypes().user_unblacklist
            )

        embed = Embed(
            title=f"User {type.capitalize()}",
            timestamp=datetime.datetime.now(),
        )

        if user.avatar:
            embed.set_thumbnail(url=user.avatar.url)

        embed.add_field(
            name="User Mention",
            value=user.mention,
            inline=False,
        )

        embed.add_field(
            name="User ID",
            value=f"``{user.id}``",
            inline=False,
        )

        embed.add_field(
            name="Staff Mention",
            value=f"{ctx.author.mention}",
            inline=False,
        )

        embed.add_field(
            name="Staff ID",
            value=f"``{ctx.author.id}``",
            inline=False,
        )

        embed.add_field(
            name="Reason",
            value=reason,
            inline=False,
        )

        with suppress(HTTPException):
            return await channel.send(
                embed=embed, silent=True
            )


class DevAmount(Converter):
    async def convert(self, ctx: Context, argument: str):
        argument = argument.replace(",", "").lower()
        multipliers = {
            "k": 1_000,
            "m": 1_000_000,
            "b": 1_000_000_000,
            "t": 1_000_000_000_000,
        }

        wallet_balance = (
            await ctx.bot.pool.fetchrow(
                "SELECT wallet FROM economy WHERE user_id = $1",
                ctx.author.id,
            )
        )["wallet"]

        if argument[-1] in multipliers:
            num_part = argument[:-1]
            suffix = argument[-1]
            try:
                amount = int(
                    float(num_part) * multipliers[suffix]
                )
                if amount <= 0:
                    raise BadArgument(
                        "Amount must be positive!"
                    )
                return amount
            except ValueError:
                raise BadArgument("Invalid amount format!")

        try:
            amount = int(argument)
            if amount <= 0:
                raise BadArgument(
                    "Amount must be positive!"
                )
            if amount > wallet_balance:
                raise BadArgument(
                    "You don't have enough money in your wallet!"
                )
            return amount
        except ValueError:
            raise BadArgument("Invalid amount format!")
