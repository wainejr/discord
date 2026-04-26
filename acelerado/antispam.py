"""Cross-channel anti-spam (issue #31).

Spam bots typically post the same payload across several channels in a
few seconds before they're banned. This module tracks a per-user sliding
window of ``(channel_id, content_hash, timestamp)`` and reacts when a
user posts in N distinct channels (or repeats the same content across
channels) inside the window.

Layout follows ``moderation.py``:

- :func:`detect_cross_channel_spam` — pure, easy to unit-test.
- :func:`handle_message_for_spam` — async coroutine called from the
  bot's ``on_message`` listener.
- A small in-memory ``defaultdict[user_id, deque]`` tracks recent
  history; a separate dict tracks per-user alert cooldowns. Restart
  resets both — that's an acceptable tradeoff for v1.

The whole thing is opt-in via ``ACELERADO_ANTISPAM_ENABLED``; defaults
chosen so an admin can flip it on, watch alerts in the mods channel,
and only escalate to ``delete``/``timeout`` once they've confirmed zero
false positives on their server.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass

import discord
from discord.ext import commands

from acelerado.env import get_env

logger = logging.getLogger(__name__)

# How many entries we keep per user. Bigger than any reasonable window
# at the configured threshold, so pruning by timestamp is the real
# bound. Cap protects memory if a user is exceptionally chatty.
_MAX_HISTORY_PER_USER = 50


@dataclass(frozen=True)
class HistoryEntry:
    channel_id: int
    content_hash: str
    timestamp: float


@dataclass(frozen=True)
class SpamSignal:
    user_id: int
    distinct_channels: int
    repeated_content: bool
    window_seconds: float
    channel_ids: tuple[int, ...]


_history: dict[int, deque[HistoryEntry]] = defaultdict(lambda: deque(maxlen=_MAX_HISTORY_PER_USER))
_alert_last_sent: dict[int, float] = {}


def reset_caches() -> None:
    """Test helper — clear in-memory tracking between tests."""
    _history.clear()
    _alert_last_sent.clear()


def _hash_content(content: str) -> str:
    # Normalize whitespace + case so trivial variants of the same paste
    # collide. Hash kept short — collisions don't matter, equality does.
    normalized = " ".join(content.lower().split())
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]


def _parse_channel_whitelist(raw: str) -> set[int]:
    out: set[int] = set()
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            out.add(int(token))
        except ValueError:
            logger.warning(f"Ignoring non-numeric antispam whitelist entry: {token!r}")
    return out


def detect_cross_channel_spam(
    history: list[HistoryEntry] | deque[HistoryEntry],
    *,
    now: float,
    window_seconds: float = 30.0,
    threshold: int = 3,
) -> SpamSignal | None:
    """Return a signal if ``history`` looks like cross-channel spam.

    Pure function, deterministic, no I/O. Fires when:
    - the user posted in ``threshold`` or more distinct channels within
      ``window_seconds``, OR
    - the user posted the same content in ≥2 distinct channels within
      the window (the "copy-paste" vector — high-precision indicator).
    """
    cutoff = now - window_seconds
    fresh = [h for h in history if h.timestamp >= cutoff]
    if not fresh:
        return None

    distinct_channels = {h.channel_id for h in fresh}
    n_distinct = len(distinct_channels)

    # Repeated-content signal: any single content_hash showed up in 2+
    # distinct channels. This is the lower-FPR path, so we fire on it
    # earlier than the raw distinct-channels threshold.
    by_hash: dict[str, set[int]] = defaultdict(set)
    for h in fresh:
        by_hash[h.content_hash].add(h.channel_id)
    repeated = any(len(channels) >= 2 for channels in by_hash.values())

    if not repeated and n_distinct < threshold:
        return None

    # We don't carry the user_id in HistoryEntry to keep it small; the
    # caller (``handle_message_for_spam``) re-stamps it before acting.
    return SpamSignal(
        user_id=0,
        distinct_channels=n_distinct,
        repeated_content=repeated,
        window_seconds=window_seconds,
        channel_ids=tuple(sorted(distinct_channels)),
    )


def _prune(user_id: int, now: float, window_seconds: float) -> None:
    """Drop entries older than the window. Called on every record."""
    history = _history[user_id]
    cutoff = now - window_seconds
    while history and history[0].timestamp < cutoff:
        history.popleft()
    if not history:
        # Reclaim memory for inactive users; defaultdict will recreate
        # on next access.
        _history.pop(user_id, None)


def _record(user_id: int, entry: HistoryEntry, window_seconds: float) -> deque[HistoryEntry]:
    _history[user_id].append(entry)
    _prune(user_id, entry.timestamp, window_seconds)
    return _history[user_id]


def _is_exempt(message: discord.Message) -> bool:
    """Mods, bots and webhook posts are never tracked."""
    author = message.author
    if author.bot:
        return True
    perms = getattr(author, "guild_permissions", None)
    if perms is not None and perms.manage_messages:
        return True
    return False


async def _send_alert(
    bot: commands.Bot,
    message: discord.Message,
    signal: SpamSignal,
) -> None:
    """Post a structured embed in the mods channel.

    Cooldown is enforced per-user so 10 messages in a burst don't yield
    10 identical alerts. We only post if at least
    ``ACELERADO_ANTISPAM_ALERT_COOLDOWN_SECONDS`` has elapsed since the
    last alert for this user.
    """
    now = time.time()
    cooldown = float(get_env().ACELERADO_ANTISPAM_ALERT_COOLDOWN_SECONDS)
    last = _alert_last_sent.get(signal.user_id)
    if last is not None and now - last < cooldown:
        return
    _alert_last_sent[signal.user_id] = now

    mods_id = get_env().DISCORD_MODS_CHANNEL_ID
    if not mods_id:
        logger.warning("antispam alert fired but DISCORD_MODS_CHANNEL_ID is not set")
        return
    mods_channel = bot.get_channel(mods_id)
    if not isinstance(mods_channel, discord.abc.Messageable):
        logger.warning(f"antispam: mods channel {mods_id} not messageable")
        return

    author = message.author
    age_days: int | None = None
    created_at = getattr(author, "created_at", None)
    if isinstance(created_at, _dt.datetime):
        age_days = max(0, (_dt.datetime.now(_dt.UTC) - created_at).days)

    channels_field = ", ".join(f"<#{cid}>" for cid in signal.channel_ids) or "—"
    embed = discord.Embed(
        title="🚨 Possível spam cross-channel",
        color=discord.Color.orange(),
    )
    embed.add_field(name="Usuário", value=author.mention, inline=False)
    embed.add_field(
        name="Canais",
        value=f"{signal.distinct_channels} distintos: {channels_field}",
        inline=False,
    )
    embed.add_field(
        name="Conteúdo repetido?",
        value="sim" if signal.repeated_content else "não",
        inline=True,
    )
    embed.add_field(
        name="Janela",
        value=f"{int(signal.window_seconds)}s",
        inline=True,
    )
    if age_days is not None:
        embed.add_field(name="Conta criada há", value=f"{age_days} dia(s)", inline=True)
    embed.add_field(
        name="Última mensagem",
        value=(message.content or "*sem texto*")[:500],
        inline=False,
    )
    if hasattr(message, "jump_url"):
        embed.add_field(name="Link", value=message.jump_url, inline=False)

    await mods_channel.send(embed=embed)


async def _delete_recent_duplicates(
    bot: commands.Bot,
    message: discord.Message,
) -> None:
    """Delete the triggering message; cross-posted copies in other
    channels are best-effort because we don't keep handles to them.

    For v1 we delete the latest message (the one that crossed the
    threshold). The first copy stays as evidence.
    """
    try:
        await message.delete()
    except discord.HTTPException as exc:
        logger.warning(f"antispam: failed to delete message {message.id}: {exc}")


async def _apply_timeout(message: discord.Message) -> None:
    member = message.author
    minutes = get_env().ACELERADO_ANTISPAM_TIMEOUT_MINUTES
    if not isinstance(member, discord.Member):
        # discord.User has no timeout method — only Members in a guild
        # can be timed out.
        logger.warning("antispam: timeout requested but author is not a Member")
        return
    until = _dt.datetime.now(_dt.UTC) + _dt.timedelta(minutes=minutes)
    try:
        await member.timeout(until, reason="antispam: cross-channel spam")
    except discord.HTTPException as exc:
        logger.warning(f"antispam: failed to timeout {member}: {exc}")


async def handle_message_for_spam(
    bot: commands.Bot,
    message: discord.Message,
) -> None:
    """Track ``message`` and react if it trips the cross-channel detector.

    Safe to call on every message — exempt cases short-circuit early.
    Never raises: errors are logged so the bot's ``on_message`` doesn't
    have to wrap us in a guard.
    """
    try:
        env = get_env()
        if not env.ACELERADO_ANTISPAM_ENABLED:
            return
        if message.guild is None:
            return  # DMs aren't cross-channel by definition
        if _is_exempt(message):
            return

        whitelist = _parse_channel_whitelist(env.ACELERADO_ANTISPAM_CHANNEL_WHITELIST)
        channel_id = getattr(message.channel, "id", None)
        if channel_id is None or channel_id in whitelist:
            return

        window = float(env.ACELERADO_ANTISPAM_WINDOW_SECONDS)
        threshold = env.ACELERADO_ANTISPAM_CROSS_CHANNEL_THRESHOLD
        now = time.time()

        entry = HistoryEntry(
            channel_id=channel_id,
            content_hash=_hash_content(message.content or ""),
            timestamp=now,
        )
        history = _record(message.author.id, entry, window)

        signal = detect_cross_channel_spam(
            history,
            now=now,
            window_seconds=window,
            threshold=threshold,
        )
        if signal is None:
            return

        # Re-stamp with the real user id (the pure detector is keyless).
        signal = SpamSignal(
            user_id=message.author.id,
            distinct_channels=signal.distinct_channels,
            repeated_content=signal.repeated_content,
            window_seconds=signal.window_seconds,
            channel_ids=signal.channel_ids,
        )

        action = (env.ACELERADO_ANTISPAM_ACTION or "alert").lower()
        await _send_alert(bot, message, signal)
        if action == "delete":
            await _delete_recent_duplicates(bot, message)
        elif action == "timeout":
            await _delete_recent_duplicates(bot, message)
            await _apply_timeout(message)
        # "alert" is the default and only logs the embed.

        logger.info(
            f"antispam fired for user={message.author.id} "
            f"channels={signal.distinct_channels} "
            f"repeated={signal.repeated_content} action={action}"
        )
    except Exception:
        logger.exception("antispam: unexpected error in handle_message_for_spam")
