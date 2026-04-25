"""Moderation primitives: anti-spam invites + ``/report`` plumbing.

Pure helpers (regex match, whitelist parsing, rate-limit bookkeeping)
sit alongside the two coroutines the bot dispatches:

- ``handle_message_for_invites(bot, message)`` — called from
  ``Bot.on_message``. Detects external Discord invite codes, verifies
  via ``bot.fetch_invite``, deletes + alerts when not whitelisted.
- ``deliver_report(bot, reporter, message, reason)`` — called from the
  ``/report`` slash command. Posts a structured embed in the mods
  channel; raises :class:`ReportRateLimited` when the reporter is over
  the per-user limit.

Both follow the fail-proof contract: every Discord-side failure is
either expected (Forbidden on DM/delete) and silently logged, or
allowed to bubble up so the bot's outer guard reports it.
"""

from __future__ import annotations

import logging
import re
import time
from collections import defaultdict, deque

import discord
from discord.ext import commands

from acelerado.env import get_env

logger = logging.getLogger(__name__)

INVITE_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?(?:discord\.gg|discord\.com/invite|discordapp\.com/invite)"
    r"/([a-zA-Z0-9-]+)",
    re.IGNORECASE,
)

# In-memory cache for resolved invite codes -> (guild_id, expires_at).
# A guild_id of None means "invalid/expired invite" so we don't re-fetch.
_INVITE_CACHE: dict[str, tuple[int | None, float]] = {}
_INVITE_CACHE_TTL = 300.0  # 5 minutes

# Per-user report rate limit: at most N reports per WINDOW seconds.
_REPORT_RATE_WINDOW = 600.0  # 10 minutes
_REPORT_RATE_MAX = 3
_report_history: dict[int, deque[float]] = defaultdict(deque)


# ---------------------------------------------------------------------------
# Helpers (pure)
# ---------------------------------------------------------------------------


def parse_whitelist(value: str) -> set[int]:
    """Parse ``ACELERADO_INVITE_WHITELIST`` (comma-separated ints) → set."""
    out: set[int] = set()
    for raw in value.split(","):
        item = raw.strip()
        if not item:
            continue
        try:
            out.add(int(item))
        except ValueError:
            logger.warning(f"Invalid guild id in invite whitelist: {item!r}")
    return out


def reset_caches() -> None:
    """Test helper — clear in-memory caches between tests."""
    _INVITE_CACHE.clear()
    _report_history.clear()


# ---------------------------------------------------------------------------
# Anti-spam invites
# ---------------------------------------------------------------------------


async def _resolve_invite_guild_id(bot: commands.Bot, code: str) -> int | None:
    """Return the guild id of an invite code, cached. None if invalid/expired."""
    now = time.time()
    cached = _INVITE_CACHE.get(code)
    if cached is not None and cached[1] > now:
        return cached[0]

    try:
        invite = await bot.fetch_invite(code, with_counts=False, with_expiration=False)
    except (discord.NotFound, discord.HTTPException):
        _INVITE_CACHE[code] = (None, now + _INVITE_CACHE_TTL)
        return None

    guild_id = invite.guild.id if invite.guild is not None else None
    _INVITE_CACHE[code] = (guild_id, now + _INVITE_CACHE_TTL)
    return guild_id


async def handle_message_for_invites(bot: commands.Bot, message: discord.Message) -> None:
    """Inspect a message; delete + alert if it has an external Discord invite.

    No-op for: bots, mods (``manage_messages``), DMs, the bot itself.
    """
    if message.author.bot or message.guild is None:
        return
    if isinstance(message.author, discord.Member) and (
        message.author.guild_permissions.manage_messages
    ):
        return

    matches = INVITE_PATTERN.findall(message.content or "")
    if not matches:
        return

    own_guild_id = message.guild.id
    whitelist = parse_whitelist(get_env().ACELERADO_INVITE_WHITELIST)
    allowed_ids = whitelist | {own_guild_id}

    blocked = False
    for code in matches:
        target = await _resolve_invite_guild_id(bot, code)
        if target is not None and target not in allowed_ids:
            blocked = True
            break

    if not blocked:
        return

    # Best-effort delete + DM. Forbidden / NotFound are expected (msg already
    # gone, no permission, DMs blocked) — log and move on.
    try:
        await message.delete()
    except (discord.Forbidden, discord.NotFound) as exc:
        logger.info(f"Could not delete invite message {message.id}: {exc}")

    try:
        await message.author.send(
            f"⚠️ Sua mensagem em **{message.guild.name}** foi removida porque "
            f"continha um convite pra outro servidor Discord. Por favor, evite "
            f"divulgar convites externos."
        )
    except (discord.Forbidden, discord.HTTPException) as exc:
        logger.info(f"Could not DM invite-blocked author: {exc}")

    mods_id = get_env().DISCORD_MODS_CHANNEL_ID
    if mods_id:
        mods_channel = bot.get_channel(mods_id)
        if isinstance(mods_channel, discord.abc.Messageable):
            await mods_channel.send(
                f"🚫 Convite externo bloqueado de {message.author.mention} "
                f"em <#{message.channel.id}>:\n```\n{(message.content or '')[:500]}\n```"
            )


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
