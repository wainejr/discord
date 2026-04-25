"""Tests for ``acelerado.moderation`` — invite filter + report rate limit."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from acelerado import moderation


@pytest.fixture(autouse=True)
def _reset_moderation_caches():
    moderation.reset_caches()


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_invite_pattern_matches_common_forms():
    s = (
        "Olha esse server: https://discord.gg/aBc123 e esse "
        "discord.com/invite/abc99 e o discordapp.com/invite/old-form"
    )
    matches = moderation.INVITE_PATTERN.findall(s)
    assert "aBc123" in matches
    assert "abc99" in matches
    assert "old-form" in matches


def test_invite_pattern_ignores_clean_text():
    assert moderation.INVITE_PATTERN.findall("nothing related here") == []
    assert moderation.INVITE_PATTERN.findall("plain http://example.com link") == []


def test_parse_whitelist():
    assert moderation.parse_whitelist("") == set()
    assert moderation.parse_whitelist("123,456") == {123, 456}
    assert moderation.parse_whitelist("123, 456 , 789") == {123, 456, 789}
    # Invalid entries are ignored
    assert moderation.parse_whitelist("123,foo,456") == {123, 456}


# ---------------------------------------------------------------------------
# Anti-spam invite handler
# ---------------------------------------------------------------------------


def _make_message(
    *,
    content: str,
    author_is_bot: bool = False,
    author_can_manage: bool = False,
    guild_id: int = 100,
) -> MagicMock:
    msg = MagicMock(spec=discord.Message)
    msg.id = 7777
    msg.content = content
    msg.delete = AsyncMock()
    msg.jump_url = "https://discord.com/channels/100/200/7777"

    author = MagicMock(spec=discord.Member)
    author.bot = author_is_bot
    author.mention = "<@1>"
    author.id = 1
    author.send = AsyncMock()
    perms = MagicMock()
    perms.manage_messages = author_can_manage
    author.guild_permissions = perms
    msg.author = author

    guild = MagicMock(spec=discord.Guild)
    guild.id = guild_id
    guild.name = "Test Guild"
    msg.guild = guild

    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 200
    msg.channel = channel
    return msg


def _make_bot_with_invite_resolution(invite_guild_id: int | None) -> MagicMock:
    """Bot mock whose fetch_invite returns an Invite pointing at ``invite_guild_id``."""
    bot = MagicMock()

    if invite_guild_id is None:

        async def fake_fetch(*args: Any, **kwargs: Any):
            raise discord.NotFound(MagicMock(status=404), "no such invite")

    else:

        async def fake_fetch(*args: Any, **kwargs: Any):
            inv = MagicMock()
            inv.guild = MagicMock()
            inv.guild.id = invite_guild_id
            return inv

    bot.fetch_invite = fake_fetch
    bot.get_channel = MagicMock(return_value=None)
    return bot


async def test_invite_handler_no_invite_in_message_is_noop():
    bot = MagicMock()
    msg = _make_message(content="só uma conversa qualquer")
    await moderation.handle_message_for_invites(bot, msg)
    msg.delete.assert_not_awaited()


async def test_invite_handler_skips_bots():
    bot = MagicMock()
    msg = _make_message(content="discord.gg/abc", author_is_bot=True)
    await moderation.handle_message_for_invites(bot, msg)
    msg.delete.assert_not_awaited()


async def test_invite_handler_skips_mods():
    bot = MagicMock()
    msg = _make_message(content="discord.gg/abc", author_can_manage=True)
    await moderation.handle_message_for_invites(bot, msg)
    msg.delete.assert_not_awaited()


async def test_invite_handler_blocks_external_invite(monkeypatch):
    monkeypatch.setenv("DISCORD_MODS_CHANNEL_ID", "0")  # mods channel disabled
    from acelerado import env as env_mod

    env_mod.get_env.cache_clear()

    bot = _make_bot_with_invite_resolution(invite_guild_id=999)
    msg = _make_message(content="https://discord.gg/badguys", guild_id=100)
    await moderation.handle_message_for_invites(bot, msg)

    msg.delete.assert_awaited_once()
    msg.author.send.assert_awaited_once()


async def test_invite_handler_allows_own_guild_invite():
    bot = _make_bot_with_invite_resolution(invite_guild_id=100)
    msg = _make_message(content="discord.gg/internal", guild_id=100)
    await moderation.handle_message_for_invites(bot, msg)

    msg.delete.assert_not_awaited()


async def test_invite_handler_respects_whitelist(monkeypatch):
    monkeypatch.setenv("ACELERADO_INVITE_WHITELIST", "555,999")
    monkeypatch.setenv("DISCORD_MODS_CHANNEL_ID", "0")
    from acelerado import env as env_mod

    env_mod.get_env.cache_clear()

    bot = _make_bot_with_invite_resolution(invite_guild_id=999)
    msg = _make_message(content="discord.gg/partner", guild_id=100)
    await moderation.handle_message_for_invites(bot, msg)

    msg.delete.assert_not_awaited()


async def test_invite_handler_invalid_invite_does_not_block():
    """fetch_invite raises NotFound (expired invite) — don't act."""
    bot = _make_bot_with_invite_resolution(invite_guild_id=None)
    msg = _make_message(content="discord.gg/expired-link")
    await moderation.handle_message_for_invites(bot, msg)
    msg.delete.assert_not_awaited()


async def test_invite_handler_logs_to_mods_channel(monkeypatch):
    monkeypatch.setenv("DISCORD_MODS_CHANNEL_ID", "777")
    from acelerado import env as env_mod

    env_mod.get_env.cache_clear()

    mods_channel = MagicMock(spec=discord.TextChannel)
    mods_channel.send = AsyncMock()

    bot = _make_bot_with_invite_resolution(invite_guild_id=999)
    bot.get_channel = MagicMock(return_value=mods_channel)

    msg = _make_message(content="discord.gg/bad", guild_id=100)
    await moderation.handle_message_for_invites(bot, msg)

    mods_channel.send.assert_awaited_once()
    body = mods_channel.send.await_args.args[0]
    assert "bloqueado" in body.lower()


# ---------------------------------------------------------------------------
# /report rate-limit + delivery
# ---------------------------------------------------------------------------


def test_rate_limit_allows_first_three():
    for _ in range(3):
        assert moderation._check_report_rate_limit(42) is True
    assert moderation._check_report_rate_limit(42) is False


def test_rate_limit_isolated_per_user():
    for _ in range(3):
        assert moderation._check_report_rate_limit(1) is True
    # Different user is unaffected.
    assert moderation._check_report_rate_limit(2) is True


def _make_report_setup(monkeypatch, mods_id: int = 777):
    monkeypatch.setenv("DISCORD_MODS_CHANNEL_ID", str(mods_id))
    from acelerado import env as env_mod

    env_mod.get_env.cache_clear()

    mods_channel = MagicMock(spec=discord.TextChannel)
    mods_channel.send = AsyncMock()

    bot = MagicMock()
    bot.get_channel = MagicMock(return_value=mods_channel if mods_id else None)

    reporter = MagicMock(spec=discord.Member)
    reporter.id = 99
    reporter.mention = "<@99>"

    target = MagicMock(spec=discord.Message)
    target.content = "mensagem ofensiva"
    target.author = MagicMock()
    target.author.mention = "<@66>"
    target.channel = MagicMock()
    target.channel.id = 200
    target.jump_url = "https://discord.com/channels/100/200/300"
    return bot, reporter, target, mods_channel


async def test_deliver_report_posts_embed(monkeypatch):
    bot, reporter, target, mods_channel = _make_report_setup(monkeypatch)

    msg = await moderation.deliver_report(bot, reporter, target, reason="spam")
    assert "✅" in msg

    mods_channel.send.assert_awaited_once()
    embed = mods_channel.send.await_args.kwargs["embed"]
    field_names = {f.name for f in embed.fields}
    assert {"Reportador", "Autor da mensagem", "Canal", "Conteúdo", "Motivo", "Link"} <= field_names


async def test_deliver_report_returns_warning_when_no_mods_channel(monkeypatch):
    bot, reporter, target, _ = _make_report_setup(monkeypatch, mods_id=0)
    msg = await moderation.deliver_report(bot, reporter, target, reason="oi")
    assert "não configurado" in msg.lower()


async def test_deliver_report_raises_after_rate_limit(monkeypatch):
    bot, reporter, target, _ = _make_report_setup(monkeypatch)

    for _ in range(moderation._REPORT_RATE_MAX):
        await moderation.deliver_report(bot, reporter, target)

    with pytest.raises(moderation.ReportRateLimited):
        await moderation.deliver_report(bot, reporter, target)
