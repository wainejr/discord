"""Tests for ``acelerado.welcome``."""

from __future__ import annotations

import random
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from acelerado import welcome

# ---------------------------------------------------------------------------
# Template loading
# ---------------------------------------------------------------------------


def test_load_strips_comments_and_blanks(tmp_path: Path):
    p = tmp_path / "msgs.txt"
    p.write_text("# top comment\n\nBem-vindo, {member}!\n  \n# another comment\nOlá {member}\n")
    assert welcome.load_welcome_messages(p) == ["Bem-vindo, {member}!", "Olá {member}"]


def test_load_returns_default_when_file_missing(tmp_path: Path):
    p = tmp_path / "missing.txt"
    assert welcome.load_welcome_messages(p) == [welcome.DEFAULT_WELCOME]


def test_load_returns_default_when_file_only_has_comments(tmp_path: Path):
    p = tmp_path / "only_comments.txt"
    p.write_text("# nothing here\n#\n# meta\n")
    assert welcome.load_welcome_messages(p) == [welcome.DEFAULT_WELCOME]


def test_real_pool_in_repo_loads_at_least_5_lines():
    """Sanity: the shipped templates/welcome_messages.txt has a real pool."""
    real = Path(__file__).resolve().parent.parent / "templates" / "welcome_messages.txt"
    if not real.exists():
        pytest.skip("templates/welcome_messages.txt not present in this checkout")
    msgs = welcome.load_welcome_messages(real)
    assert len(msgs) >= 5
    # All shipped templates use known placeholders only
    for m in msgs:
        m.format(member="<@1>", guild="g", channel_youtube="https://x")


# ---------------------------------------------------------------------------
# Render + pick
# ---------------------------------------------------------------------------


def _fake_member(name: str = "alice", member_id: int = 99) -> MagicMock:
    m = MagicMock(spec=discord.Member)
    m.name = name
    m.id = member_id
    m.mention = f"<@{member_id}>"
    m.bot = False
    m.send = AsyncMock()
    return m


def _fake_guild(name: str = "Guildão") -> MagicMock:
    g = MagicMock(spec=discord.Guild)
    g.name = name
    return g


def test_render_substitutes_all_placeholders():
    member = _fake_member()
    guild = _fake_guild()
    rendered = welcome.render_welcome(
        "Olá {member}, bem-vindo a {guild}! Canal: {channel_youtube}",
        member,
        guild,
    )
    assert "<@99>" in rendered
    assert "Guildão" in rendered
    assert welcome.YOUTUBE_CHANNEL_URL in rendered


def test_pick_is_deterministic_with_seeded_rng():
    pool = ["A {member}", "B {member}", "C {member}", "D {member}"]
    member = _fake_member()
    guild = _fake_guild()

    rng = random.Random(42)
    first = welcome.pick_welcome(member, guild, pool=pool, rng=rng)

    rng = random.Random(42)  # same seed
    second = welcome.pick_welcome(member, guild, pool=pool, rng=rng)

    assert first == second


# ---------------------------------------------------------------------------
# handle_join — channel/DM branches
# ---------------------------------------------------------------------------


def _fake_bot_with_channel(channel) -> MagicMock:
    bot = MagicMock()
    bot.get_channel = MagicMock(return_value=channel)
    return bot


async def test_handle_join_posts_to_configured_channel(monkeypatch):
    monkeypatch.setenv("DISCORD_WELCOME_CHANNEL_ID", "12345")
    from acelerado import env as env_mod

    env_mod.get_env.cache_clear()

    channel = MagicMock(spec=discord.TextChannel)
    channel.send = AsyncMock()
    bot = _fake_bot_with_channel(channel)

    member = _fake_member()
    member.guild = _fake_guild()
    await welcome.handle_join(bot, member)

    channel.send.assert_awaited_once()
    member.send.assert_not_awaited()


async def test_handle_join_falls_back_to_dm_when_channel_id_zero(monkeypatch):
    # default ACELERADO env doesn't set welcome channel
    monkeypatch.setenv("DISCORD_WELCOME_CHANNEL_ID", "0")
    from acelerado import env as env_mod

    env_mod.get_env.cache_clear()

    bot = _fake_bot_with_channel(None)
    member = _fake_member()
    member.guild = _fake_guild()
    await welcome.handle_join(bot, member)

    member.send.assert_awaited_once()


async def test_handle_join_dm_blocked_is_silently_logged(monkeypatch, caplog):
    monkeypatch.setenv("DISCORD_WELCOME_CHANNEL_ID", "0")
    from acelerado import env as env_mod

    env_mod.get_env.cache_clear()

    bot = _fake_bot_with_channel(None)
    member = _fake_member()
    member.guild = _fake_guild()
    member.send.side_effect = discord.Forbidden(MagicMock(status=403), "DMs disabled")

    # Must not raise
    with caplog.at_level("INFO", logger="acelerado.welcome"):
        await welcome.handle_join(bot, member)
    assert any("DMs blocked" in r.message for r in caplog.records)


async def test_handle_join_skips_other_bots():
    bot = _fake_bot_with_channel(None)
    member = _fake_member()
    member.bot = True
    member.guild = _fake_guild()

    await welcome.handle_join(bot, member)
    member.send.assert_not_awaited()


async def test_handle_join_falls_back_when_channel_id_set_but_invalid(monkeypatch):
    """If the configured channel id resolves to None or non-Messageable, fall back to DM."""
    monkeypatch.setenv("DISCORD_WELCOME_CHANNEL_ID", "999")
    from acelerado import env as env_mod

    env_mod.get_env.cache_clear()

    bot = _fake_bot_with_channel(None)  # get_channel returns None
    member = _fake_member()
    member.guild = _fake_guild()
    await welcome.handle_join(bot, member)

    member.send.assert_awaited_once()
