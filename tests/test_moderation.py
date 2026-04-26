"""Tests for ``acelerado.moderation`` — /report rate limit + delivery."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from acelerado import moderation


@pytest.fixture(autouse=True)
def _reset_moderation_caches():
    moderation.reset_caches()


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
