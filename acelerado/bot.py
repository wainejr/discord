import logging

import discord
from discord.ext import commands, tasks

from acelerado import welcome
from acelerado.env import get_env
from acelerado.slash import register_commands
from acelerado.state import AceleradoState

logger = logging.getLogger(__name__)


class AceleradoBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.members = True
        super().__init__(command_prefix="/", intents=intents)
        self.state_handler: AceleradoState | None = None

    async def setup_hook(self) -> None:
        # `tasks.loop` locks its interval at decorator-time; bump it to the
        # configured value before the first tick.
        self.event_loop_task.change_interval(seconds=get_env().ACELERADO_TICK_SECONDS)
        self.event_loop_task.start()

        # Register slash commands and sync them guild-scoped — propagates
        # instantly, unlike global sync (~1h). Bot is single-guild today.
        guild = discord.Object(id=get_env().DISCORD_GUILD_ID)
        register_commands(self.tree, guild=guild)
        try:
            synced = await self.tree.sync(guild=guild)
            logger.info(f"Synced {len(synced)} slash command(s) to guild {guild.id}")
        except Exception:
            logger.exception("Failed to sync slash commands; bot will run without them")

    async def on_ready(self) -> None:
        logger.info(f"Logged on as {self.user}!")
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="Waine - Dev do Desempenho",
            )
        )
        logger.info("Updated presence!")

    async def on_member_join(self, member: discord.Member) -> None:
        try:
            await welcome.handle_join(self, member)
        except Exception as exc:
            if self.state_handler is not None:
                await self.state_handler.report_error("welcome", exc)
            else:
                logger.exception(f"welcome failed before state_handler ready: {exc}")

    async def on_error(self, event_method: str, /, *args, **kwargs) -> None:
        """Replace the default stderr dump with a proper log line.

        Gateway-level errors (anything raised inside an event handler that
        we didn't catch ourselves) land here. We log with traceback and,
        if the state handler is up, report to the Discord log channel.
        """
        import sys

        exc = sys.exc_info()[1]
        logger.exception(f"Unhandled error in event {event_method!r}")
        if self.state_handler is not None and exc is not None:
            try:
                await self.state_handler.report_error(f"event:{event_method}", exc)
            except Exception:
                logger.exception("report_error itself failed")

    @tasks.loop(seconds=300)
    async def event_loop_task(self) -> None:
        # AceleradoState.event_loop already swallows per-step errors and
        # reports them. Anything escaping here is a bug in the glue itself
        # — we log + report but never re-raise, so the tasks.Loop keeps
        # firing on schedule.
        try:
            if self.state_handler is None:
                logger.error("event_loop_task fired with no state_handler; skipping")
                return
            await self.state_handler.event_loop()
        except Exception as exc:
            logger.exception("Unexpected crash in event_loop_task")
            if self.state_handler is not None:
                try:
                    await self.state_handler.report_error("event_loop_task", exc)
                except Exception:
                    logger.exception("report_error itself failed")

    @event_loop_task.before_loop
    async def _before_event_loop(self) -> None:
        await self.wait_until_ready()
        if self.state_handler is None:
            self.state_handler = AceleradoState(self)

    @event_loop_task.error
    async def _event_loop_error(self, exc: BaseException) -> None:
        # Belt-and-suspenders: the body above already catches Exception,
        # but discord.py stops the loop on any escaping BaseException.
        # Log, try to report, then restart so we don't silently die.
        logger.exception("event_loop_task errored out — restarting", exc_info=exc)
        if self.state_handler is not None and isinstance(exc, Exception):
            try:
                await self.state_handler.report_error("event_loop_task:fatal", exc)
            except Exception:
                logger.exception("report_error itself failed")
        self.event_loop_task.restart()


def run_bot() -> None:
    bot = AceleradoBot()
    bot.run(get_env().DISCORD_TOKEN, log_handler=None)
