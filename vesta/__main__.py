import logging
import os
import psutil
import asyncio
import argparse

from cashews import cache
from contextlib import suppress
from os import getenv, environ

from vesta.framework import Vesta
from vesta.shared.config import Configuration

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("vesta.log"),
    ],
)

logger = logging.getLogger("vesta")

process = psutil.Process(os.getpid())
logger.info(
    f"Starting Vesta process with PID: {os.getpid()} [Parent: {process.ppid()}]"
)

cache.setup(getenv("REDIS_URL", "redis://localhost:6379/2"))

environ["JISHAKU_NO_UNDERSCORE"] = "True"
environ["JISHAKU_NO_DM_TRACEBACK"] = "True"
environ["JISHAKU_HIDE"] = "True"
environ["JISHAKU_FORCE_PAGINATOR"] = "True"
environ["JISHAKU_RETAIN"] = "True"


async def main():

    bot = Vesta(
        Configuration(),
    )

    async with bot:
        await bot.start()


if __name__ == "__main__":
    with suppress(RuntimeError, KeyboardInterrupt, ProcessLookupError):
        asyncio.run(main())
