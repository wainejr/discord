"""Tests for ``acelerado.slash`` — registration + response shape.

We avoid instantiating the full ``AceleradoBot`` (which would try to
connect to the gateway). A bare ``discord.Client`` is fine — its
constructor doesn't open any sockets.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import discord
from discord import app_commands

from acelerado.slash import LINKS, cmd_links, register_commands


def _build_tree() -> app_commands.CommandTree:
    intents = discord.Intents.default()
    client = discord.Client(intents=intents)
    return app_commands.CommandTree(client)


def test_register_links_command_globally():
    tree = _build_tree()
    register_commands(tree)

    cmd = tree.get_command("links")
    assert cmd is not None
    assert cmd.name == "links"
    assert cmd.description  # non-empty


def test_register_links_command_guild_scoped():
    tree = _build_tree()
    guild = discord.Object(id=12345)
    register_commands(tree, guild=guild)

    # Guild-scoped commands aren't visible without passing guild=
    assert tree.get_command("links") is None
    assert tree.get_command("links", guild=guild) is not None


async def test_links_command_sends_ephemeral_embed():
    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    # cmd_links is wrapped by @app_commands.command; invoke its callback directly.
    await cmd_links.callback(interaction)

    interaction.response.send_message.assert_awaited_once()
    kwargs = interaction.response.send_message.await_args.kwargs
    assert kwargs.get("ephemeral") is True

    embed = kwargs.get("embed")
    assert isinstance(embed, discord.Embed)
    field_names = {f.name for f in embed.fields}
    assert field_names == set(LINKS.keys())
    field_values = {f.value for f in embed.fields}
    assert field_values == set(LINKS.values())


def test_links_dict_uses_https_urls():
    """All links in the embed point to HTTPS — guard against accidental http://."""
    for name, url in LINKS.items():
        assert url.startswith("https://"), f"{name} has non-https URL: {url}"


# ---------------------------------------------------------------------------
# /sync admin command
# ---------------------------------------------------------------------------


def test_register_sync_command_guild_scoped():
    tree = _build_tree()
    guild = discord.Object(id=1)
    register_commands(tree, guild=guild)

    cmd = tree.get_command("sync", guild=guild)
    assert cmd is not None
    assert cmd.name == "sync"
    # Admin permission gate is set via the decorator.
    assert cmd.default_permissions is not None
    assert cmd.default_permissions.administrator is True


def _make_sync_interaction(bot):
    interaction = MagicMock(spec=discord.Interaction)
    interaction.client = bot
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    return interaction


async def test_sync_command_reports_count_when_added(monkeypatch):
    from acelerado import bot as bot_mod
    from acelerado.slash import cmd_sync

    fake_bot = MagicMock(spec=bot_mod.AceleradoBot)
    fake_bot.state_handler = MagicMock()
    fake_bot.state_handler.check_members_apoiadores = AsyncMock(return_value=3)

    interaction = _make_sync_interaction(fake_bot)
    await cmd_sync.callback(interaction)

    interaction.response.defer.assert_awaited_once()
    interaction.followup.send.assert_awaited_once()
    msg = interaction.followup.send.await_args.args[0]
    assert "3" in msg
    assert "Sync concluído" in msg


async def test_sync_command_zero_added_message():
    from acelerado import bot as bot_mod
    from acelerado.slash import cmd_sync

    fake_bot = MagicMock(spec=bot_mod.AceleradoBot)
    fake_bot.state_handler = MagicMock()
    fake_bot.state_handler.check_members_apoiadores = AsyncMock(return_value=0)

    interaction = _make_sync_interaction(fake_bot)
    await cmd_sync.callback(interaction)

    msg = interaction.followup.send.await_args.args[0]
    assert "nenhum membro pendente" in msg.lower()


async def test_sync_command_reports_failure():
    from acelerado import bot as bot_mod
    from acelerado.slash import cmd_sync

    fake_bot = MagicMock(spec=bot_mod.AceleradoBot)
    fake_bot.state_handler = MagicMock()
    fake_bot.state_handler.check_members_apoiadores = AsyncMock(side_effect=RuntimeError("kaboom"))
    fake_bot.state_handler.report_error = AsyncMock()

    interaction = _make_sync_interaction(fake_bot)
    await cmd_sync.callback(interaction)

    fake_bot.state_handler.report_error.assert_awaited_once()
    msg = interaction.followup.send.await_args.args[0]
    assert "❌" in msg
    assert "RuntimeError" in msg


async def test_sync_command_handles_uninitialized_bot():
    """If the slash fires before setup_hook finishes, respond gracefully."""
    from acelerado.slash import cmd_sync

    # Plain Mock — not an AceleradoBot instance, so isinstance returns False.
    fake_bot = MagicMock()
    interaction = _make_sync_interaction(fake_bot)
    await cmd_sync.callback(interaction)

    interaction.response.send_message.assert_awaited_once()
    msg = interaction.response.send_message.await_args.args[0]
    assert "ainda não" in msg.lower()


# ---------------------------------------------------------------------------
# /update admin command
# ---------------------------------------------------------------------------


def test_register_update_command():
    tree = _build_tree()
    guild = discord.Object(id=1)
    register_commands(tree, guild=guild)

    cmd = tree.get_command("update", guild=guild)
    assert cmd is not None
    assert cmd.default_permissions is not None
    assert cmd.default_permissions.administrator is True


def _make_update_interaction():
    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    return interaction


async def test_update_command_clean_no_restart(monkeypatch):
    from acelerado import slash, updater
    from acelerado.slash import cmd_update

    monkeypatch.setattr(
        updater,
        "apply_updates",
        lambda repo=None: updater.UpdateResult(status="clean", message="up to date"),
    )

    # Sentinel: ensure _delayed_exit not scheduled on clean.
    exit_calls = []
    monkeypatch.setattr(slash, "_delayed_exit", lambda *a, **kw: exit_calls.append(a))

    interaction = _make_update_interaction()
    await cmd_update.callback(interaction)

    interaction.followup.send.assert_awaited_once()
    msg = interaction.followup.send.await_args.args[0]
    assert "Nada pra atualizar" in msg
    assert exit_calls == []


async def test_update_command_conflict_no_restart(monkeypatch):
    from acelerado import slash, updater
    from acelerado.slash import cmd_update

    monkeypatch.setattr(
        updater,
        "apply_updates",
        lambda repo=None: updater.UpdateResult(status="conflict", message="would be overwritten"),
    )
    exit_calls = []
    monkeypatch.setattr(slash, "_delayed_exit", lambda *a, **kw: exit_calls.append(a))

    interaction = _make_update_interaction()
    await cmd_update.callback(interaction)

    msg = interaction.followup.send.await_args.args[0]
    assert "Conflito" in msg
    assert exit_calls == []


async def test_update_command_ok_schedules_restart(monkeypatch):
    import asyncio

    from acelerado import slash, updater
    from acelerado.slash import cmd_update

    monkeypatch.setattr(
        updater,
        "apply_updates",
        lambda repo=None: updater.UpdateResult(
            status="ok",
            head="newhash1234",
            commits=["c1 first commit", "c2 second commit"],
            message="Updated",
        ),
    )

    scheduled: list[Any] = []

    async def fake_delayed_exit(code, delay_seconds=3.0):
        scheduled.append((code, delay_seconds))

    monkeypatch.setattr(slash, "_delayed_exit", fake_delayed_exit)

    interaction = _make_update_interaction()
    await cmd_update.callback(interaction)

    msg = interaction.followup.send.await_args.args[0]
    assert "Atualizado pra" in msg
    assert "newhash" in msg
    # A restart was scheduled
    await asyncio.sleep(0)  # let the create_task run
    assert len(scheduled) == 1
    assert scheduled[0][0] == updater.EXIT_RESTART
