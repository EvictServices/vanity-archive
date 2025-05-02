import logging
import glob
import os
import importlib
import json
from io import BytesIO

from datetime import datetime, timezone
from typing import List, Optional
from pathlib import Path
from aiohttp import ClientSession

from discord import (
    Intents,
    Message,
    Guild,
    AuditLogEntry,
    HTTPException,
    Activity,
    ActivityType,
    AllowedMentions,
)
from discord.ext.commands import (
    AutoShardedBot,
    ExtensionError,
)
from discord.ext.tasks import loop

from vesta.framework.discord import (
    Context,
    CommandErrorHandler,
)
from vesta.framework.discord.checks import is_blacklisted
from vesta.framework.pagination import Paginator

from vesta.shared.config import (
    Authentication,
    Configuration,
)
from vesta.shared.clients import postgres
from vesta.shared.clients.postgres import Database
from vesta.shared.clients.redis import Redis


logger = logging.getLogger("vesta/main")


class Vesta(AutoShardedBot):
    """
    Custom bot class that extends AutoShardedBot.
    """
    database: Database
    redis: Redis
    session: ClientSession

    def __init__(
        self,
        Configuration: Configuration,
    ):
        super().__init__(
            command_prefix=self.get_prefix,
            help_command=None,
            case_insensitive=True,
            strip_after_prefix=True,
            owner_ids=Authentication.owner_ids,
            intents=Intents.all(),
            allowed_mentions=AllowedMentions(
                everyone=False,
                roles=False,
                users=True,
                replied_user=False,
            ),
            activity=Activity(
                type=ActivityType.streaming,
                name="🔗 evict.bot",
                url=f"https://twitch.tv/evict",
            ),
        )
        self.uptime = datetime.now(timezone.utc)

    def get_message(
        self, message_id: int
    ) -> Optional[Message]:
        """
        Fetch a message from the cache.
        """
        return self._connection._get_message(message_id)

    async def get_guild_prefix(self, guild_id: int) -> str:
        cache_key = f"prefix:guild:{guild_id}"

        if cached := await self.redis.get(cache_key):
            return cached

        if res := await self.pool.fetchrow(
            """
            SELECT prefix FROM settings 
            WHERE guild_id = $1
            """,
            guild_id,
        ):
            prefix = (
                res["prefix"]
                or Configuration().defaults.prefix
            )
            if prefix:
                await self.redis.set(
                    cache_key, prefix, ex=3600
                )
            return prefix

        return Configuration().defaults.prefix

    async def get_user_prefix(
        self, user_id: int
    ) -> Optional[str]:
        cache_key = f"prefix:user:{user_id}"

        if cached := await self.redis.get(cache_key):
            return cached

        if res := await self.pool.fetchrow(
            'SELECT prefix FROM "user".settings WHERE user_id = $1',
            user_id,
        ):
            prefix = res["prefix"]
            if prefix:
                await self.redis.set(
                    cache_key, prefix, ex=3600
                )
            return prefix

        return None

    async def get_prefix(
        self, message: Message
    ) -> List[str]:
        if not message.guild:
            return [self.Configuration.defaults.prefix]

        prefixes = []

        guild_prefix = await self.get_guild_prefix(
            message.guild.id
        )
        user_prefix = await self.get_user_prefix(
            message.author.id
        )

        if guild_prefix:
            prefixes.append(guild_prefix)
        if user_prefix:
            prefixes.append(user_prefix)
        if not prefixes:
            prefixes.append(
                self.Configuration.defaults.prefix
            )

        return [str(prefix) for prefix in prefixes]

    async def update_guild_prefix(
        self, guild_id: int, prefix: str
    ) -> None:
        await self.pool.execute(
            """
            INSERT INTO settings (guild_id, prefix)
            VALUES ($1, $2)
            ON CONFLICT (guild_id) 
            DO UPDATE SET prefix = $2
            """,
            guild_id,
            prefix,
        )
        if prefix:
            await self.redis.set(
                f"prefix:guild:{guild_id}", prefix, ex=3600
            )
        else:
            await self.redis.delete(
                f"prefix:guild:{guild_id}"
            )

    async def update_user_prefix(
        self, user_id: int, prefix: Optional[str] = None
    ) -> None:
        if prefix is None:
            await self.pool.execute(
                'UPDATE "user".settings SET prefix = NULL WHERE user_id = $1',
                user_id,
            )
            await self.redis.delete(
                f"prefix:user:{user_id}"
            )
        else:
            await self.pool.execute(
                """
                INSERT INTO "user".settings (user_id, prefix)
                VALUES ($1, $2)
                ON CONFLICT (user_id) 
                DO UPDATE SET prefix = $2
                """,
                user_id,
                prefix,
            )
            await self.redis.set(
                f"prefix:user:{user_id}", prefix, ex=3600
            )

    async def on_ready(
        self,
    ):
        logger.info(
            f"Logged in as {self.user} (ID: {self.user.id})"
        )
        await self.upload_commands_task.start()
        await self.upload_stats_task.start()
        if self.shard_id:
            shard_guilds = sum(
                1
                for guild in self.guilds
                if guild.shard_id == self.shard_id
            )
            logger.info(
                f"Shard: {self.shard_id + 1}/{self.shard_count} with {shard_guilds} guild(s)"
            )

    async def on_shard_ready(self, shard_id: int) -> None:
        """
        Custom on_shard_ready method that logs shard status.
        """
        try:
            guilds_in_shard = len([
                g
                for g in self.guilds
                if (g.id >> 22) % self.shard_count
                == shard_id
            ])
            logger.info(
                f"Shard {shard_id} ready: Serving {guilds_in_shard:,} guilds"
            )

            if shard_id == self.shard_count - 1:
                total_guilds = len(self.guilds)
                uptime_delta = (
                    datetime.now(timezone.utc) - self.uptime
                ).total_seconds()

                logger.info(
                    f"All {self.shard_count} shards connected ({uptime_delta:.2f}s): "
                    f"Serving {total_guilds:,} guilds"
                )

        except Exception as e:
            logger.error(
                f"Error in on_shard_ready for shard {shard_id}: {e}",
                exc_info=True,
            )

    async def on_shard_resumed(self, shard_id: int) -> None:
        """
        Custom on_shard_resumed method that logs shard status.
        """
        logger.info(f"Shard ID {shard_id} has resumed .")

    async def notify(
        self, guild: Guild, *args, **kwargs
    ) -> Optional[Message]:
        """
        Send a message to the first available channel.
        """
        if not isinstance(guild, Guild):
            logger.error(
                f"Expected Guild object, got {type(guild).__name__}"
            )
            return

        if (
            guild.system_channel
            and guild.system_channel.permissions_for(
                guild.me
            ).send_messages
        ):
            try:
                return await guild.system_channel.send(
                    *args, **kwargs
                )
            except HTTPException:
                return

        for channel in guild.text_channels:
            if channel.permissions_for(
                guild.me
            ).send_messages:
                try:
                    return await channel.send(
                        *args, **kwargs
                    )
                except HTTPException:
                    break

    async def _load_patches(self) -> None:
        """
        Load all patches in the framework directory.
        """
        for module in glob.glob(
            "vesta/framework/discord/patches/**/*.py",
            recursive=True,
        ):
            if module.endswith("__init__.py"):
                continue

            module_name = (
                module.replace(os.path.sep, ".")
                .replace("/", ".")
                .replace(".py", "")
            )
            try:
                importlib.import_module(module_name)
                logger.info(f"Patched: {module}")

            except (ModuleNotFoundError, ImportError) as e:
                logger.error(
                    f"Error importing {module_name}: {e}"
                )

    async def _load_extensions(self) -> None:
        """
        Load all plugins in the framework directory.
        """
        loaded_count = 0
        jishaku_loaded = False

        for extension in sorted(
            Path("vesta/plugins").glob("*")
        ):
            if extension.name.startswith(("_", ".")):
                continue

            package = (
                extension.stem
                if extension.is_file()
                and extension.suffix == ".py"
                else (
                    extension.name
                    if extension.is_dir()
                    and (extension / "__init__.py").exists()
                    else None
                )
            )

            if not package:
                continue

            try:
                if not jishaku_loaded:
                    await self.load_extension("jishaku")
                    jishaku_loaded = True

                await self.load_extension(
                    f"vesta.plugins.{package}"
                )

                loaded_count += 1
                logger.info(f"Loaded extension: {package}")

            except ExtensionError as exc:
                logger.error(
                    f"Failed to load extension {package}: {exc}",
                    exc_info=True,
                )

        logger.info(
            f"Successfully loaded {loaded_count} extensions."
        )

    async def setup_hook(self) -> None:
        """
        Initialize bot resources with cluster awareness
        """
        self.session = ClientSession(
            headers={
                "User-Agent": "Mozilla/5.0 (iPhone; U; CPU iPhone OS 4_0 like Mac OS X; en-us)"
                " AppleWebKit/532.9 (KHTML, like Gecko) Version/4.0.5 Mobile/8A293 Safari/6531.22.7"
            },
        )

        self.redis = await Redis.from_url()
        logger.info("Connected to Redis")

        self.database = await postgres.connect()
        logger.info("Connected to shared resources")

        await self._load_patches()
        logger.info("Loaded patches")

        await self._load_extensions()
        logger.info("Loaded packages")
        self.backend.start_task()
        logger.info("Started backend task")

        await self.minio.connect()
        logger.info("Connected to MinIO")
        return await super().setup_hook()

    async def get_context(
    self, message: Message, *, cls=Context
    ) -> Context:
        context = await super().get_context(
            message, cls=cls
        )
        if context.guild is not None:
            context.config = await Configuration.from_guild(
                context.guild.id, self
            )
        else:
            context.config = None

        return context


    async def on_command_error(
        self, context: Context, exception: Exception
    ) -> None:
        """
        Custom error handler for commands.
        """
        await CommandErrorHandler.on_command_error(
            self, context, exception
        )

    async def close(self) -> None:
        """
        Cleanup resources and close the bot
        """
        await self.session.close()
        await self.database.close()
        await self.redis.close()
        await self.backend.stop()
        await self.minio.close()
        await self.upload_commands_task.stop()
        await self.upload_stats_task.stop()

        await super().close()

    async def start(
        self, *, reconnect: bool = True
    ) -> None:  # type: ignore
        return await super().start(
            Authentication.token, reconnect=reconnect
        )

    @property
    def pool(self) -> Database:
        """
        Convenience property to access the database.
        """
        return self.database

    async def on_audit_log_entry_create(
        self, entry: AuditLogEntry
    ):
        if not self.is_ready():
            return

        event = f"audit_log_entry_{entry.action.name}"
        self.dispatch(event, entry)

    async def process_commands(self, message: Message, /):
        if message.author.bot or not message.guild:
            return

        if await is_blacklisted(
            self, message.author.id, "user"
        ) or await is_blacklisted(
            self, message.guild.id, "guild"
        ):
            return

        ctx = await self.get_context(message)
        if not ctx.valid:
            self.dispatch("message_without_command", ctx)
            return

        if ctx.valid:
            ratelimit = await self.redis.ratelimited(
                f"global:{message.author.id}",
                limit=2,
                timespan=3,
            )
            if ratelimit:
                reaction_ratelimit = (
                    await self.redis.ratelimited(
                        f"reaction:{message.author.id}",
                        limit=1,
                        timespan=3,
                    )
                )
                if not reaction_ratelimit:
                    await ctx.message.add_reaction("⏳")
                logger.warning(
                    f"ignored possible abuse: user:{message.author.id} guild:{message.guild.id} command:{ctx.command}"
                )
                return

            await self.invoke(ctx)

    @loop(minutes=30)  # this is gpt generated shit , concept is to upload commands to a s3 bucket every 30 minutes
    async def upload_commands_task(self):
        """
        Upload commands to a S3 bucket every 30 minutes
        """
        if not self.is_ready():
            return
            
        try:
            logger.info("Starting commands data upload to S3")
            commands_data = []
            
            for command in self.commands:
                # Skip commands that might cause issues
                if command.hidden:
                    continue
                    
                # Ensure all data is serializable
                aliases = [str(alias) for alias in command.aliases] if hasattr(command, "aliases") else []
                
                # Create a simpler, guaranteed serializable structure
                cmd_data = {
                    "name": str(command.name),
                    "description": str(command.description or command.help or ""),
                    "aliases": aliases,
                    "brief": str(command.brief or ""),
                    "usage": str(command.usage or ""),
                    "cog_name": str(command.cog.qualified_name) if command.cog else None,
                }
                
                # Only add subcommands if they exist
                if hasattr(command, "commands") and command.commands:
                    subcommands = []
                    for subcmd in command.commands:
                        subcmd_data = {
                            "name": str(subcmd.name),
                            "description": str(subcmd.description or subcmd.help or ""),
                        }
                        subcommands.append(subcmd_data)
                    cmd_data["subcommands"] = subcommands
                
                commands_data.append(cmd_data)
            
            # Verify serializable before continuing
            try:
                commands_json = json.dumps(commands_data, indent=2, ensure_ascii=True)
                logger.info(f"JSON serialization successful: {len(commands_data)} commands")
            except Exception as json_error:
                logger.error(f"JSON serialization failed: {json_error}")
                return
                
            buffer = BytesIO(commands_json.encode("utf-8"))
            
            # Check if system bucket exists before upload
            if not await self.minio.check_bucket_exists("system"):
                logger.info("Creating system bucket")
                await self.minio.create_bucket("system")
            
            await self.minio.upload(
                path="commands.json",
                buffer=buffer,
                bucket_name="system"
            )
            
            logger.info(f"Successfully uploaded commands data: {len(commands_data)} commands")
            
        except Exception as e:
            logger.error(f"Failed to upload commands data: {e}", exc_info=True)

    @loop(minutes=5)
    async def upload_stats_task(self):
        """
        Upload stats to a S3 bucket every 5 minutes
        """
        pass


__all__ = ("Vesta", "Context", "Paginator")
