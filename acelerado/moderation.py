"""Moderation primitives: ``/report`` plumbing.

Pure helpers (rate-limit bookkeeping) sit alongside the coroutine the
bot dispatches:

- ``deliver_report(bot, reporter, message, reason)`` — called from the
  ``/report`` slash command. Posts a structured embed in the mods
  channel; raises :class:`ReportRateLimited` when the reporter is over
  the per-user limit.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque

import discord
from discord.ext import commands

from acelerado.env import get_env

logger = logging.getLogger(__name__)

# Per-user report rate limit: at most N reports per WINDOW seconds.
_REPORT_RATE_WINDOW = 600.0  # 10 minutes
_REPORT_RATE_MAX = 3
_report_history: dict[int, deque[float]] = defaultdict(deque)


def reset_caches() -> None:
    """Test helper — clear in-memory state between tests."""
    _report_history.clear()


# ---------------------------------------------------------------------------
# /report
# ---------------------------------------------------------------------------


class ReportRateLimited(Exception):
    """Raised when a reporter exceeds 3 reports per 10 min."""


def _check_report_rate_limit(user_id: int) -> bool:
    """Record a call. Return False if the user is over the limit."""
    now = time.time()
    history = _report_history[user_id]
    while history and history[0] < now - _REPORT_RATE_WINDOW:
        history.popleft()
    if len(history) >= _REPORT_RATE_MAX:
        return False
    history.append(now)
    return True


async def deliver_report(
    bot: commands.Bot,
    reporter: discord.User | discord.Member,
    message: discord.Message,
    reason: str | None = None,
) -> str:
    """Post a structured embed about ``message`` to the mods channel.

    Returns the human-readable status string (intended to flow into an
    ephemeral reply). Raises :class:`ReportRateLimited` when the
    reporter has hit the per-user limit.
    """
    if not _check_report_rate_limit(reporter.id):
        raise ReportRateLimited()

    mods_id = get_env().DISCORD_MODS_CHANNEL_ID
    if not mods_id:
        return "⚠️ Canal de mods não configurado. Avise um admin."
    mods_channel = bot.get_channel(mods_id)
    if not isinstance(mods_channel, discord.abc.Messageable):
        return "⚠️ Canal de mods não acessível."

    embed = discord.Embed(title="🚩 Mensagem reportada", color=discord.Color.red())
    embed.add_field(name="Reportador", value=reporter.mention, inline=False)
    embed.add_field(name="Autor da mensagem", value=message.author.mention, inline=False)
    embed.add_field(name="Canal", value=f"<#{message.channel.id}>", inline=False)
    embed.add_field(
        name="Conteúdo",
        value=(message.content or "*sem texto*")[:1000],
        inline=False,
    )
    if reason:
        embed.add_field(name="Motivo", value=reason[:500], inline=False)
    embed.add_field(name="Link", value=message.jump_url, inline=False)

    await mods_channel.send(embed=embed)
    return "✅ Reportado pros mods. Obrigado!"
