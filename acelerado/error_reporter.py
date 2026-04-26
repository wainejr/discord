"""Rate-limited error reporting to Discord.

Pulled out of ``AceleradoState`` so the cooldown logic is testable in
isolation and so the same reporter can be reused by other parts of the
bot (e.g. weekly tasks) without dragging the whole state with them.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import discord

from acelerado import metrics

logger = logging.getLogger(__name__)

# How often we're willing to post a "something blew up" report to Discord.
# Local logs are always emitted; this only throttles the remote notification
# so a broken tick doesn't spam the log channel every 5 minutes.
ERROR_REPORT_COOLDOWN = timedelta(minutes=10)


ChannelGetter = Callable[[], "discord.abc.Messageable | None"]


class ErrorReporter:
    """Logs locally, optionally posts to a Discord channel with cooldown."""

    def __init__(self, channel_getter: ChannelGetter) -> None:
        self._get_channel = channel_getter
        self.last_report = datetime.now(UTC) - timedelta(days=7)

    async def report(self, context: str, exc: BaseException) -> None:
        logger.exception(f"[{context}] {type(exc).__name__}: {exc}", exc_info=exc)
        metrics.increment("errors", context=context)

        now = datetime.now(UTC)
        if now - self.last_report < ERROR_REPORT_COOLDOWN:
            return
        self.last_report = now

        channel = self._get_channel()
        if channel is None:
            return

        summary = f"⚠️ Erro em `{context}`: `{type(exc).__name__}: {exc}`"
        # Discord caps messages at 2000 chars; leave headroom.
        if len(summary) > 1900:
            summary = summary[:1900] + "…"
        try:
            await channel.send(summary)
        except Exception:
            # A failing notifier must never bubble up — we already logged locally.
            logger.exception("Failed to deliver error report to Discord log channel")
