import logging

import discord
from discord.ext import commands, tasks

from acelerado.env import get_env
from acelerado.state import AceleradoState

logger = logging.getLogger(__name__)


class AceleradoBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.members = True
        super().__init__(command_prefix="/", intents=intents)
        self.state_handler: AceleradoState | None = None

    async def setup_hook(self) -> None:
        self.event_loop_task.start()

    async def on_ready(self) -> None:
        logger.info(f"Logged on as {self.user}!")
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="Waine - Dev do Desempenho",
            )
        )
        logger.info("Updated presence!")

    @tasks.loop(seconds=300)
    async def event_loop_task(self) -> None:
        try:
            await self.state_handler.event_loop()
        except Exception:
            logger.exception("Error on event loop")

    @event_loop_task.before_loop
    async def _before_event_loop(self) -> None:
        await self.wait_until_ready()
        if self.state_handler is None:
            self.state_handler = AceleradoState(self)


def run_bot() -> None:
    bot = AceleradoBot()
    bot.run(get_env().DISCORD_TOKEN, log_handler=None)
