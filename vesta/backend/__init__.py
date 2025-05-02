from __future__ import annotations

import asyncio
import aiohttp_cors

from dataclasses import asdict
from datetime import datetime, timezone
from logging import getLogger
from typing import (
    TYPE_CHECKING,
    ParamSpec,
    TypeVar,
    no_type_check,
)

from aiohttp import web, ClientSession, ClientError
from aiohttp.abc import AbstractAccessLogger
from aiohttp.web import Application, Response, Request

from vesta.framework.tools import (
    GuildPayload,
    MemberPayload,
    ThreadPayload,
    TextChannelPayload,
    ForumChannelPayload,
    StageChannelPayload,
    VoiceChannelPayload,
    PrivateChannelPayload,
    CategoryChannelPayload,
)

if TYPE_CHECKING:
    from vesta.framework import Vesta


logger = getLogger("vesta/backend")
T = TypeVar("T", bound=Response)
P = ParamSpec("P")


class AccessLogger(AbstractAccessLogger):
    def log(
        self,
        request: web.BaseRequest,
        response: web.StreamResponse,
        time: float,
    ) -> None:
        if response.status in (404, 302):
            return

        path = request.path

        if request.method == "HEAD" or time <= 0.001:
            return

        logger.info(
            "{method} {path} {code} {size} {ms:0.0f}ms".format(
                method=request.method,
                path=path,
                code=response.status,
                size=self.format_size(response.body_length),
                ms=time * 1000,
            )
        )

    @staticmethod
    def format_size(num):
        if num >= 1024**2:
            return "{:0.1f}MB".format(num / 1024**2)
        elif num >= 1024:
            return "{:0.1f}KB".format(num / 1024)
        else:
            return "{:0.0f}B".format(num)


class Backend(Application):
    bot: Vesta
    task: asyncio.Task
    heartbeat_task: asyncio.Task
    _started: bool = False
    last_heartbeat: datetime = datetime.now()

    @no_type_check
    def __init__(
        self, bot: Vesta, port: int, *args, **kwargs
    ):
        super().__init__(*args, **kwargs, logger=logger)
        self.cors = aiohttp_cors.setup(
            self,
            defaults={
                "*": aiohttp_cors.ResourceOptions(
                    allow_credentials=True,
                    expose_headers="*",
                    allow_headers="*",
                )
            },
        )
        self.bot = bot
        self.port = port
        self.router.add_get("/", self.index)
        self.router.add_get("/health", self.health)
        self.router.add_post("/heartbeat", self.heartbeat)
        self.router.add_post("/guild/find", self.guild_find)
        self.router.add_post(
            "/guild/channel", self.get_channel
        )
        self.router.add_get(
            "/guilds/list", self.list_guilds
        )
        self.router.add_post("/reload", self.reload)
        self._started = False
        self.heartbeat_task = None
        self.session = None

    def setup_cors(self):
        for route in list(self.router.routes()):
            self.cors.add(route)

    def start_task(self):
        if not self._started:
            self.task = asyncio.create_task(
                self.start(), name="backend"
            )
            self.task.add_done_callback(
                self._handle_task_exception
            )
            self.heartbeat_task = asyncio.create_task(
                self._heartbeat_loop(), name="heartbeat"
            )
            self.heartbeat_task.add_done_callback(
                self._handle_task_exception
            )
            self._started = True
            logger.info("Backend task started")

    def _handle_task_exception(self, task: asyncio.Task):
        if task.exception():
            logger.error(
                "Unhandled exception in backend task",
                exc_info=task.exception(),
            )

    async def start(self):
        self.setup_cors()

        try:
            await web._run_app(
                self,
                host="localhost",
                port=self.port,
                access_log=logger,
                access_log_class=AccessLogger,
                print=None,
            )
        except OSError as e:
            logger.error(
                f"Backend failed to start http://localhost:{self.port}",
                exc_info=e,
            )
            self._started = False

    async def stop(self):
        await self.shutdown()
        await self.cleanup()
        if self.session:
            await self.session.close()
        self.task.cancel()
        if self.heartbeat_task:
            self.heartbeat_task.cancel()

    async def index(self, request: Request):
        return Response(text="Backend")

    async def health(self, request: Request) -> Response:
        return web.json_response({
            "status": "healthy",
            "last_heartbeat": self.last_heartbeat.isoformat(),
            "uptime": (
                datetime.now(timezone.utc) - self.bot.uptime
            ).total_seconds(),
        })

    async def heartbeat(self, request: Request) -> Response:
        self.last_heartbeat = datetime.now()
        return Response(text="Heartbeat received")

    async def guild_find(
        self, request: Request
    ) -> Response:
        if not (data := await request.json()) or not (
            user_id := data.get("user_id")
        ):
            return Response(
                status=400, text="Missing user_id"
            )

        member = await self.bot.get_member(user_id)
        if not member:
            return Response(
                status=404, text="Member not found"
            )

        return web.json_response(
            MemberPayload.from_member(member).__dict__
        )

    async def get_channel(
        self, request: Request
    ) -> Response:
        if not (data := await request.json()) or not (
            channel_id := data.get("channel_id")
        ):
            return Response(
                status=400, text="Missing channel_id"
            )

        if not (
            channel := self.bot.get_channel(channel_id)
        ):
            return Response(
                status=404, text="Channel not found"
            )

        payload_map = {
            "Thread": ThreadPayload.from_thread,
            "TextChannel": TextChannelPayload.from_text_channel,
            "VoiceChannel": VoiceChannelPayload.from_voice_channel,
            "StageChannel": StageChannelPayload.from_stage_channel,
            "ForumChannel": ForumChannelPayload.from_forum_channel,
            "CategoryChannel": CategoryChannelPayload.from_category_channel,
            "PrivateChannel": PrivateChannelPayload.from_private_channel,
        }
        channel_type = channel.__class__.__name__
        if channel_type in payload_map:
            payload = payload_map[channel_type](channel)
        else:
            return Response(
                status=400,
                text=f"Unsupported channel type: {channel_type}",
            )

        return web.json_response({
            "type": channel_type,
            "data": payload.__dict__,
        })

    async def list_guilds(
        self, request: Request
    ) -> Response:
        return web.json_response({
            "guilds": [
                asdict(GuildPayload.from_guild(guild))
                for guild in self.bot.guilds
            ]
        })

    async def reload(self, request: Request) -> Response:
        data = await request.json()
        if not data:
            logger.info("NO NIGGA DATA?")

        if not data or not data.get("extension"):
            logger.info(
                f"Invalid Extension name {data.get('extension')}"
            )
            return Response(
                status=400, text="Missing extension name"
            )

        await self.bot.reload_extension(
            data.get("extension")
        )
        return Response(
            text="Extension reloaded successfully"
        )

    async def _heartbeat_loop(self):
        self.session = ClientSession()
        while True:
            try:
                await self._send_heartbeat()
            except (ClientError, asyncio.TimeoutError) as e:
                logger.error(
                    "Failed to send heartbeat", exc_info=e
                )
            await asyncio.sleep(5)

    async def _send_heartbeat(self):
        if not self.session:
            return

        shards = [
            {
                "id": shard.id,
                "latency": shard.latency,
                "guilds": sum(
                    1
                    for guild in self.bot.guilds
                    if guild.shard_id == shard.id
                ),
                "uptime": (
                    datetime.now(timezone.utc)
                    - self.bot.uptime
                ).total_seconds(),
                "bots": sum(
                    1 for m in self.bot.users if m.bot
                ),
                "humans": sum(
                    1 for m in self.bot.users if not m.bot
                ),
                "users": len(self.bot.users),
            }
            for shard in self.bot.shards.values()
        ]

        async with self.session.post(
            "http://localhost:6978/heartbeat",
            json={
                "id": self.bot.cluster_id,
                "shards": shards,
            },
        ) as resp:
            if not resp.ok:
                logger.error(
                    f"Heartbeat failed with status {resp.status}"
                )
