"""Tests for ``acelerado.review`` — pure builders, lightly the posters."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from acelerado import review

# ---------------------------------------------------------------------------
# Weekly summary builder
# ---------------------------------------------------------------------------


def _video(video_id: str, title: str, days_ago: float, views: int = 0) -> dict:
    when = datetime.now(UTC) - timedelta(days=days_ago)
    iso = when.isoformat().replace("+00:00", "Z")
    return {
        "id": video_id,
        "snippet": {"title": title, "publishedAt": iso},
        "statistics": {"viewCount": str(views)},
    }


def test_summary_empty_when_no_recent_videos():
    text = review.build_weekly_summary_text([_video("old", "Antigo", days_ago=20)])
    assert "Nenhum vídeo novo" in text


def test_summary_lists_videos_in_window():
    videos = [
        _video("a", "Video A", days_ago=2),
        _video("b", "Video B", days_ago=5),
        _video("c", "Velho", days_ago=15),  # outside window
    ]
    text = review.build_weekly_summary_text(videos)
    assert "Video A" in text
    assert "Video B" in text
    assert "Velho" not in text
    # Count line
    assert "**2 vídeos novos:**" in text


def test_summary_includes_top_when_stats_present():
    videos = [
        _video("a", "Top vídeo", days_ago=1, views=10000),
        _video("b", "Médio", days_ago=2, views=500),
        _video("c", "Baixo", days_ago=3, views=10),
    ]
    text = review.build_weekly_summary_text(videos)
    assert "🏆 Top da semana" in text
    assert "Top vídeo" in text


def test_summary_omits_top_when_no_stats():
    # No statistics -> no top section
    videos = [{"id": "x", "snippet": {"title": "x", "publishedAt": "2026-04-25T00:00:00Z"}}]
    text = review.build_weekly_summary_text(videos)
    assert "🏆 Top" not in text


# ---------------------------------------------------------------------------
# Stale apoiadores builder
# ---------------------------------------------------------------------------


def _make_role(name: str) -> MagicMock:
    r = MagicMock(spec=discord.Role)
    r.name = name
    r.members = []
    return r


def _make_member(name: str, member_id: int, roles: list) -> MagicMock:
    m = MagicMock(spec=discord.Member)
    m.name = name
    m.id = member_id
    m.mention = f"<@{member_id}>"
    m.roles = roles
    return m


def test_find_stale_returns_empty_when_role_missing():
    guild = MagicMock(spec=discord.Guild)
    guild.roles = [_make_role("@everyone")]
    assert review.find_stale_apoiadores(guild) == []


def test_find_stale_lists_members_without_yt_role(monkeypatch):
    monkeypatch.setenv("ACELERADO_APOIADORES_WHITELIST", "")
    from acelerado import env as env_mod

    env_mod.get_env.cache_clear()

    apoiadores = _make_role("Registradores")
    yt_t1 = _make_role("YouTube Member (Nível 1)")

    alice = _make_member("alice", 1, [apoiadores])  # stale
    bob = _make_member("bob", 2, [apoiadores, yt_t1])  # OK
    apoiadores.members = [alice, bob]

    guild = MagicMock(spec=discord.Guild)
    guild.roles = [apoiadores, yt_t1]

    stale = review.find_stale_apoiadores(guild)
    assert [m.id for m in stale] == [1]


def test_find_stale_respects_whitelist(monkeypatch):
    monkeypatch.setenv("ACELERADO_APOIADORES_WHITELIST", "alice,carol")
    from acelerado import env as env_mod

    env_mod.get_env.cache_clear()

    apoiadores = _make_role("Registradores")
    alice = _make_member("alice", 1, [apoiadores])
    bob = _make_member("bob", 2, [apoiadores])
    apoiadores.members = [alice, bob]

    guild = MagicMock(spec=discord.Guild)
    guild.roles = [apoiadores]

    stale = review.find_stale_apoiadores(guild)
    # alice whitelisted, bob remains
    assert [m.name for m in stale] == ["bob"]


def test_format_stale_report_empty():
    out = review.format_stale_report([])
    assert "Nenhum apoiador stale" in out


def test_format_stale_report_with_members():
    apoiadores = _make_role("Registradores")
    members = [_make_member("alice", 1, [apoiadores]), _make_member("bob", 2, [apoiadores])]
    out = review.format_stale_report(members)
    assert "<@1>" in out
    assert "<@2>" in out
    assert "alice" in out
    assert "bob" in out


def test_parse_username_whitelist():
    assert review.parse_username_whitelist("") == set()
    assert review.parse_username_whitelist("a, b ,c") == {"a", "b", "c"}


# ---------------------------------------------------------------------------
# Posters — high-level: missing config returns warning
# ---------------------------------------------------------------------------


async def test_post_weekly_summary_no_review_channel_returns_warning(monkeypatch):
    monkeypatch.setenv("DISCORD_REVIEW_CHANNEL_ID", "0")
    from acelerado import env as env_mod

    env_mod.get_env.cache_clear()

    bot = MagicMock()
    msg = await review.post_weekly_summary_draft(bot)
    assert "não configurado" in msg.lower()


async def test_post_stale_report_no_target_returns_warning(monkeypatch):
    monkeypatch.setenv("DISCORD_MODS_CHANNEL_ID", "0")
    monkeypatch.setenv("DISCORD_REVIEW_CHANNEL_ID", "0")
    from acelerado import env as env_mod

    env_mod.get_env.cache_clear()

    bot = MagicMock()
    msg = await review.post_stale_report(bot)
    assert "configurado" in msg.lower()


async def test_post_stale_report_posts_message(monkeypatch):
    monkeypatch.setenv("DISCORD_MODS_CHANNEL_ID", "555")
    from acelerado import env as env_mod

    env_mod.get_env.cache_clear()

    apoiadores = _make_role("Registradores")
    apoiadores.members = []

    guild = MagicMock(spec=discord.Guild)
    guild.roles = [apoiadores]

    target = MagicMock(spec=discord.TextChannel)
    target.send = AsyncMock()

    bot = MagicMock()
    bot.get_channel = MagicMock(return_value=target)
    bot.get_guild = MagicMock(return_value=guild)

    msg = await review.post_stale_report(bot)
    target.send.assert_awaited_once()
    assert "Nenhum apoiador stale" in target.send.await_args.args[0]
    assert "✅" in msg


@pytest.mark.parametrize("cmd_name", ["preview-summary", "preview-stale"])
def test_admin_preview_commands_are_registered(cmd_name):
    """Sanity: register_commands wires both preview slashes guild-scoped."""
    from acelerado.slash import register_commands

    intents = discord.Intents.default()
    client = discord.Client(intents=intents)
    tree = discord.app_commands.CommandTree(client)
    guild = discord.Object(id=42)
    register_commands(tree, guild=guild)

    assert tree.get_command(cmd_name, guild=guild) is not None
