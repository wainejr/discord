"""Tests for ``acelerado.antispam`` — cross-channel spam detector (issue #31)."""

from __future__ import annotations

import datetime as _dt
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from acelerado import antispam


@pytest.fixture(autouse=True)
def _reset_antispam_caches():
    antispam.reset_caches()


# ---------------------------------------------------------------------------
# Pure detector
# ---------------------------------------------------------------------------


def _entry(channel_id: int, content: str = "x", ts: float = 0.0) -> antispam.HistoryEntry:
    return antispam.HistoryEntry(
        channel_id=channel_id,
        content_hash=antispam._hash_content(content),
        timestamp=ts,
    )


def test_detector_returns_none_on_empty_history():
    assert antispam.detect_cross_channel_spam([], now=100.0) is None


def test_detector_returns_none_below_threshold_and_no_repeat():
    history = [_entry(1, "hello world", ts=99.0), _entry(2, "totally different", ts=99.5)]
    assert (
        antispam.detect_cross_channel_spam(history, now=100.0, window_seconds=30.0, threshold=3)
        is None
    )


def test_detector_fires_on_distinct_channel_threshold():
    history = [
        _entry(1, "a", ts=80.0),
        _entry(2, "b", ts=85.0),
        _entry(3, "c", ts=90.0),
    ]
    sig = antispam.detect_cross_channel_spam(history, now=100.0, window_seconds=30.0, threshold=3)
    assert sig is not None
    assert sig.distinct_channels == 3
    assert sig.channel_ids == (1, 2, 3)


def test_detector_fires_on_repeated_content_in_two_channels():
    history = [
        _entry(1, "buy crypto now", ts=98.0),
        _entry(2, "buy crypto now", ts=99.0),
    ]
    sig = antispam.detect_cross_channel_spam(history, now=100.0, window_seconds=30.0, threshold=10)
    assert sig is not None
    assert sig.repeated_content is True
    assert sig.distinct_channels == 2


def test_detector_normalizes_whitespace_and_case():
    # Same payload modulo case + spacing collides on hash.
    h1 = antispam._hash_content("Buy Crypto NOW!")
    h2 = antispam._hash_content("buy   crypto    now!")
    assert h1 == h2


def test_detector_ignores_entries_outside_window():
    history = [
        _entry(1, "a", ts=10.0),
        _entry(2, "b", ts=11.0),
        _entry(3, "c", ts=12.0),  # all far older than window
    ]
    assert (
        antispam.detect_cross_channel_spam(history, now=100.0, window_seconds=30.0, threshold=3)
        is None
    )


# ---------------------------------------------------------------------------
# History pruning
# ---------------------------------------------------------------------------


def test_record_prunes_old_entries():
    user_id = 42
    old = antispam.HistoryEntry(channel_id=1, content_hash="x", timestamp=0.0)
    fresh = antispam.HistoryEntry(channel_id=2, content_hash="y", timestamp=100.0)

    antispam._record(user_id, old, window_seconds=30.0)
    history = antispam._record(user_id, fresh, window_seconds=30.0)

    timestamps = [e.timestamp for e in history]
    assert 0.0 not in timestamps
    assert 100.0 in timestamps


# ---------------------------------------------------------------------------
# Message-handling integration (mocked discord)
# ---------------------------------------------------------------------------


def _setup_env(monkeypatch, **overrides) -> None:
    monkeypatch.setenv("ACELERADO_ANTISPAM_ENABLED", "true")
    monkeypatch.setenv("DISCORD_MODS_CHANNEL_ID", "777")
    monkeypatch.setenv("ACELERADO_ANTISPAM_WINDOW_SECONDS", "30")
    monkeypatch.setenv("ACELERADO_ANTISPAM_CROSS_CHANNEL_THRESHOLD", "3")
    monkeypatch.setenv("ACELERADO_ANTISPAM_ACTION", "alert")
    monkeypatch.setenv("ACELERADO_ANTISPAM_CHANNEL_WHITELIST", "")
    monkeypatch.setenv("ACELERADO_ANTISPAM_ALERT_COOLDOWN_SECONDS", "600")
    for k, v in overrides.items():
        monkeypatch.setenv(k, v)
    from acelerado import env as env_mod

    env_mod.get_env.cache_clear()


def _make_bot_with_mods_channel(messageable: bool = True) -> tuple[MagicMock, MagicMock]:
    if messageable:
        mods = MagicMock(spec=discord.TextChannel)
        mods.send = AsyncMock()
    else:
        mods = MagicMock(spec=object)  # not Messageable
    bot = MagicMock()
    bot.get_channel = MagicMock(return_value=mods)
    return bot, mods


def _make_message(
    *,
    channel_id: int,
    content: str = "spam",
    author_id: int = 99,
    is_mod: bool = False,
    is_bot: bool = False,
    member: bool = True,
    account_age_days: int = 30,
) -> MagicMock:
    msg = MagicMock(spec=discord.Message)
    msg.content = content
    msg.id = channel_id * 1000 + author_id
    msg.guild = MagicMock(spec=discord.Guild)
    msg.guild.id = 111
    msg.jump_url = f"https://discord.com/channels/111/{channel_id}/{msg.id}"

    chan = MagicMock(spec=discord.TextChannel)
    chan.id = channel_id
    msg.channel = chan

    author_spec = discord.Member if member else discord.User
    author = MagicMock(spec=author_spec)
    author.id = author_id
    author.bot = is_bot
    author.mention = f"<@{author_id}>"
    author.created_at = _dt.datetime.now(_dt.UTC) - _dt.timedelta(days=account_age_days)
    if member:
        perms = MagicMock()
        perms.manage_messages = is_mod
        author.guild_permissions = perms
        author.timeout = AsyncMock()
    msg.author = author
    msg.delete = AsyncMock()
    return msg


async def test_handle_skips_when_disabled(monkeypatch):
    _setup_env(monkeypatch, ACELERADO_ANTISPAM_ENABLED="false")
    bot, mods = _make_bot_with_mods_channel()
    msg = _make_message(channel_id=1)
    await antispam.handle_message_for_spam(bot, msg)
    mods.send.assert_not_awaited()


async def test_handle_skips_bots(monkeypatch):
    _setup_env(monkeypatch)
    bot, mods = _make_bot_with_mods_channel()
    for ch in (1, 2, 3):
        await antispam.handle_message_for_spam(bot, _make_message(channel_id=ch, is_bot=True))
    mods.send.assert_not_awaited()


async def test_handle_skips_mods(monkeypatch):
    _setup_env(monkeypatch)
    bot, mods = _make_bot_with_mods_channel()
    for ch in (1, 2, 3):
        await antispam.handle_message_for_spam(bot, _make_message(channel_id=ch, is_mod=True))
    mods.send.assert_not_awaited()


async def test_handle_skips_dms(monkeypatch):
    _setup_env(monkeypatch)
    bot, mods = _make_bot_with_mods_channel()
    msg = _make_message(channel_id=1)
    msg.guild = None
    await antispam.handle_message_for_spam(bot, msg)
    mods.send.assert_not_awaited()


async def test_handle_skips_whitelisted_channel(monkeypatch):
    _setup_env(monkeypatch, ACELERADO_ANTISPAM_CHANNEL_WHITELIST="1,2,3")
    bot, mods = _make_bot_with_mods_channel()
    for ch in (1, 2, 3):
        await antispam.handle_message_for_spam(bot, _make_message(channel_id=ch))
    mods.send.assert_not_awaited()


async def test_handle_alerts_on_repeated_content_cross_channel(monkeypatch):
    _setup_env(monkeypatch)
    bot, mods = _make_bot_with_mods_channel()

    # Same content posted in two channels by the same user.
    await antispam.handle_message_for_spam(bot, _make_message(channel_id=1, content="buy crypto"))
    await antispam.handle_message_for_spam(bot, _make_message(channel_id=2, content="buy crypto"))

    mods.send.assert_awaited_once()
    embed = mods.send.await_args.kwargs["embed"]
    assert "spam" in embed.title.lower()


async def test_handle_alerts_after_threshold_distinct_channels(monkeypatch):
    _setup_env(monkeypatch)
    bot, mods = _make_bot_with_mods_channel()

    # Three different posts in three different channels — but distinct
    # contents (no repeat-content match), so only the threshold fires.
    for ch, content in [(1, "alpha"), (2, "beta"), (3, "gamma")]:
        await antispam.handle_message_for_spam(bot, _make_message(channel_id=ch, content=content))

    mods.send.assert_awaited_once()


async def test_alert_includes_account_age(monkeypatch):
    _setup_env(monkeypatch)
    bot, mods = _make_bot_with_mods_channel()
    for ch in (1, 2):
        await antispam.handle_message_for_spam(
            bot, _make_message(channel_id=ch, content="same", account_age_days=2)
        )
    embed = mods.send.await_args.kwargs["embed"]
    field_names = {f.name for f in embed.fields}
    assert "Conta criada há" in field_names


async def test_alert_cooldown_prevents_flood(monkeypatch):
    _setup_env(monkeypatch)
    bot, mods = _make_bot_with_mods_channel()

    # Trip detector twice in quick succession — second alert should be
    # suppressed by the per-user cooldown.
    for ch in (1, 2):
        await antispam.handle_message_for_spam(bot, _make_message(channel_id=ch, content="same"))
    for ch in (3, 4):
        await antispam.handle_message_for_spam(bot, _make_message(channel_id=ch, content="same"))

    assert mods.send.await_count == 1


async def test_action_delete_removes_message(monkeypatch):
    _setup_env(monkeypatch, ACELERADO_ANTISPAM_ACTION="delete")
    bot, _ = _make_bot_with_mods_channel()

    msg1 = _make_message(channel_id=1, content="dup")
    msg2 = _make_message(channel_id=2, content="dup")
    await antispam.handle_message_for_spam(bot, msg1)
    await antispam.handle_message_for_spam(bot, msg2)

    # Only the triggering (second) message gets deleted in v1.
    msg2.delete.assert_awaited_once()


async def test_action_timeout_calls_member_timeout(monkeypatch):
    _setup_env(monkeypatch, ACELERADO_ANTISPAM_ACTION="timeout")
    bot, _ = _make_bot_with_mods_channel()

    msg1 = _make_message(channel_id=1, content="dup")
    msg2 = _make_message(channel_id=2, content="dup")
    await antispam.handle_message_for_spam(bot, msg1)
    await antispam.handle_message_for_spam(bot, msg2)

    msg2.author.timeout.assert_awaited_once()


async def test_action_alert_does_not_delete_or_timeout(monkeypatch):
    _setup_env(monkeypatch)  # default action=alert
    bot, _ = _make_bot_with_mods_channel()

    msg1 = _make_message(channel_id=1, content="dup")
    msg2 = _make_message(channel_id=2, content="dup")
    await antispam.handle_message_for_spam(bot, msg1)
    await antispam.handle_message_for_spam(bot, msg2)

    msg2.delete.assert_not_awaited()
    msg2.author.timeout.assert_not_awaited()


async def test_handle_swallows_unexpected_errors(monkeypatch, caplog):
    _setup_env(monkeypatch)
    bot, mods = _make_bot_with_mods_channel()
    mods.send.side_effect = RuntimeError("boom")

    # Trip detector — alert path will raise, but the handler must not.
    for ch in (1, 2):
        await antispam.handle_message_for_spam(bot, _make_message(channel_id=ch, content="same"))
    # Still only one attempted send; second was suppressed by detector
    # cooldown logic — we mainly assert no exception propagated.
    assert any("antispam" in r.message and r.levelname == "ERROR" for r in caplog.records)
