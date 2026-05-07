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


async def test_register_report_command():
    tree = _build_tree()
    guild = discord.Object(id=1)
    register_commands(tree, guild=guild)
    cmd = tree.get_command("report", guild=guild)
    assert cmd is not None
    assert cmd.name == "report"


def test_register_godbolt_command():
    tree = _build_tree()
    guild = discord.Object(id=1)
    register_commands(tree, guild=guild)
    cmd = tree.get_command("godbolt", guild=guild)
    assert cmd is not None
    assert cmd.name == "godbolt"


async def test_godbolt_command_returns_url_in_embed():
    from discord import app_commands

    from acelerado.slash import cmd_godbolt

    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    choice = app_commands.Choice(name="C", value="c")
    await cmd_godbolt.callback(interaction, language=choice, code="int main(){return 0;}")

    interaction.response.send_message.assert_awaited_once()
    embed = interaction.response.send_message.await_args.kwargs.get("embed")
    assert embed is not None
    assert "godbolt.org/clientstate/" in (embed.description or "")


async def test_report_invalid_link_responds_with_warning():
    from acelerado.slash import cmd_report

    interaction = MagicMock(spec=discord.Interaction)
    interaction.client = MagicMock()
    interaction.user = MagicMock()
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()

    await cmd_report.callback(interaction, message_link="not-a-link", reason="x")

    interaction.response.send_message.assert_awaited_once()
    msg = interaction.response.send_message.await_args.args[0]
    assert "inválido" in msg.lower()


# ---------------------------------------------------------------------------
# /config group
# ---------------------------------------------------------------------------


def test_register_config_group():
    tree = _build_tree()
    guild = discord.Object(id=1)
    register_commands(tree, guild=guild)
    cmd = tree.get_command("config", guild=guild)
    assert cmd is not None
    assert isinstance(cmd, app_commands.Group)
    sub_names = {c.name for c in cmd.commands}
    assert sub_names == {"list", "set-channel", "set", "unset"}


def _get_config_subcommand(name: str):
    tree = _build_tree()
    guild = discord.Object(id=1)
    register_commands(tree, guild=guild)
    group = tree.get_command("config", guild=guild)
    assert isinstance(group, app_commands.Group)
    for cmd in group.commands:
        if cmd.name == name:
            return cmd
    raise AssertionError(f"subcommand {name!r} not registered")


def _make_admin_interaction():
    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    return interaction


async def test_config_list_renders_embed(chdir_tmp):
    cmd = _get_config_subcommand("list")
    interaction = _make_admin_interaction()
    await cmd.callback(interaction)
    interaction.response.send_message.assert_awaited_once()
    embed = interaction.response.send_message.await_args.kwargs.get("embed")
    assert isinstance(embed, discord.Embed)
    field_names = {f.name for f in embed.fields}
    assert "ACELERADO_TICK_SECONDS" in field_names
    # Secret redaction
    rendered = " ".join(f.value or "" for f in embed.fields)
    assert "test-discord-token" not in rendered


async def test_config_list_renders_channel_keys_as_mentions(chdir_tmp):
    """Channel-typed keys must render as <#id> so they're clickable."""
    cmd = _get_config_subcommand("list")
    interaction = _make_admin_interaction()
    await cmd.callback(interaction)
    embed = interaction.response.send_message.await_args.kwargs.get("embed")
    fields = {f.name: (f.value or "") for f in embed.fields}
    # Test fixture sets DISCORD_ANNOUNCE_CHANNEL_ID=222 — should render <#222>.
    assert "<#222>" in fields["DISCORD_ANNOUNCE_CHANNEL_ID"]
    assert "<#333>" in fields["DISCORD_LOG_CHANNEL_ID"]


async def test_config_list_marks_unset_channels(chdir_tmp):
    """Channel keys defaulting to 0 should show 'não configurado', not <#0>."""
    cmd = _get_config_subcommand("list")
    interaction = _make_admin_interaction()
    await cmd.callback(interaction)
    embed = interaction.response.send_message.await_args.kwargs.get("embed")
    fields = {f.name: (f.value or "") for f in embed.fields}
    # DISCORD_WELCOME_CHANNEL_ID has no fixture override -> defaults to 0.
    welcome = fields["DISCORD_WELCOME_CHANNEL_ID"]
    assert "<#0>" not in welcome
    assert "não configurado" in welcome


async def test_config_set_channel_persists_id(chdir_tmp):
    from acelerado.config import get_settings, reload_settings

    reload_settings()
    cmd = _get_config_subcommand("set-channel")
    interaction = _make_admin_interaction()

    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 555_666_777
    choice = app_commands.Choice(name="welcome", value="DISCORD_WELCOME_CHANNEL_ID")

    await cmd.callback(interaction, key=choice, channel=channel)

    interaction.response.send_message.assert_awaited_once()
    msg = interaction.response.send_message.await_args.args[0]
    assert "555666777" in msg.replace(",", "")
    # Persisted to Settings
    assert get_settings().cfg.DISCORD_WELCOME_CHANNEL_ID == 555_666_777


async def test_config_set_invalid_value_responds_with_warning(chdir_tmp):
    from acelerado.config import reload_settings

    reload_settings()
    cmd = _get_config_subcommand("set")
    interaction = _make_admin_interaction()

    choice = app_commands.Choice(name="tick-seconds", value="ACELERADO_TICK_SECONDS")
    await cmd.callback(interaction, key=choice, value="not-an-int")

    msg = interaction.response.send_message.await_args.args[0]
    assert "inválido" in msg.lower()


async def test_config_unset_reverts_to_fallback(chdir_tmp):
    from acelerado.config import get_settings, reload_settings

    reload_settings()
    get_settings().set("ACELERADO_TICK_SECONDS", 99)
    cmd = _get_config_subcommand("unset")
    interaction = _make_admin_interaction()
    choice = app_commands.Choice(name="tick-seconds", value="ACELERADO_TICK_SECONDS")

    await cmd.callback(interaction, key=choice)
    interaction.response.send_message.assert_awaited_once()
    assert get_settings().cfg.ACELERADO_TICK_SECONDS == 300  # back to default


# ---------------------------------------------------------------------------
# /token group — owner-only OAuth renewal
# ---------------------------------------------------------------------------


def test_register_token_group():
    tree = _build_tree()
    guild = discord.Object(id=1)
    register_commands(tree, guild=guild)
    cmd = tree.get_command("token", guild=guild)
    assert cmd is not None
    assert isinstance(cmd, app_commands.Group)
    sub_names = {c.name for c in cmd.commands}
    assert sub_names == {"renew-start", "renew-finish"}


def _get_token_subcommand(name: str):
    tree = _build_tree()
    guild = discord.Object(id=1)
    register_commands(tree, guild=guild)
    group = tree.get_command("token", guild=guild)
    assert isinstance(group, app_commands.Group)
    for cmd in group.commands:
        if cmd.name == name:
            return cmd
    raise AssertionError(f"subcommand {name!r} not registered")


def _make_token_interaction(user_id: int):
    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock()
    interaction.user.id = user_id
    interaction.user.create_dm = AsyncMock()
    dm_channel = MagicMock()
    dm_channel.send = AsyncMock()
    interaction.user.create_dm.return_value = dm_channel
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    return interaction, dm_channel


async def test_token_renew_start_rejects_non_owner(monkeypatch):
    monkeypatch.setenv("DISCORD_OWNER_ID", "999")
    from acelerado.config import reload_settings

    reload_settings()
    cmd = _get_token_subcommand("renew-start")
    interaction, _ = _make_token_interaction(user_id=42)
    await cmd.callback(interaction)
    interaction.response.send_message.assert_awaited_once()
    msg = interaction.response.send_message.await_args.args[0]
    assert "dono" in msg.lower()


async def test_token_renew_start_rejects_when_owner_unset(monkeypatch):
    """Default DISCORD_OWNER_ID=0 — even matching users get refused."""
    cmd = _get_token_subcommand("renew-start")
    interaction, _ = _make_token_interaction(user_id=0)
    await cmd.callback(interaction)
    msg = interaction.response.send_message.await_args.args[0]
    assert "dono" in msg.lower()


async def test_token_renew_start_dms_url_for_owner(monkeypatch):
    monkeypatch.setenv("DISCORD_OWNER_ID", "42")
    from acelerado import youtube
    from acelerado.config import reload_settings

    reload_settings()
    monkeypatch.setattr(youtube, "start_oauth_flow", lambda uid: f"https://google/auth?uid={uid}")

    cmd = _get_token_subcommand("renew-start")
    interaction, dm_channel = _make_token_interaction(user_id=42)
    await cmd.callback(interaction)

    dm_channel.send.assert_awaited_once()
    sent = dm_channel.send.await_args.args[0]
    assert "https://google/auth?uid=42" in sent
    interaction.response.send_message.assert_awaited_once()
    assert "DM" in interaction.response.send_message.await_args.args[0]


async def test_token_renew_start_handles_blocked_dm(monkeypatch):
    monkeypatch.setenv("DISCORD_OWNER_ID", "42")
    from acelerado import youtube
    from acelerado.config import reload_settings

    reload_settings()
    monkeypatch.setattr(youtube, "start_oauth_flow", lambda uid: "https://google/auth")

    cmd = _get_token_subcommand("renew-start")
    interaction, dm_channel = _make_token_interaction(user_id=42)
    dm_channel.send.side_effect = discord.Forbidden(MagicMock(status=403), "blocked")

    await cmd.callback(interaction)
    msg = interaction.response.send_message.await_args.args[0]
    assert "DM" in msg


async def test_token_renew_finish_rejects_non_owner(monkeypatch):
    monkeypatch.setenv("DISCORD_OWNER_ID", "999")
    from acelerado.config import reload_settings

    reload_settings()
    cmd = _get_token_subcommand("renew-finish")
    interaction, _ = _make_token_interaction(user_id=42)
    await cmd.callback(interaction, redirect_url="http://localhost/?code=x&state=y")
    interaction.response.send_message.assert_awaited_once()


async def test_token_renew_finish_surfaces_value_error(monkeypatch):
    monkeypatch.setenv("DISCORD_OWNER_ID", "42")
    from acelerado import youtube
    from acelerado.config import reload_settings

    reload_settings()

    def boom(user_id, url):
        raise ValueError("State mismatch — refusing")

    monkeypatch.setattr(youtube, "complete_oauth_flow", boom)

    cmd = _get_token_subcommand("renew-finish")
    interaction, _ = _make_token_interaction(user_id=42)
    await cmd.callback(interaction, redirect_url="http://localhost/?code=x&state=evil")
    interaction.followup.send.assert_awaited_once()
    msg = interaction.followup.send.await_args.args[0]
    assert "State mismatch" in msg


async def test_token_renew_finish_happy_path(monkeypatch):
    monkeypatch.setenv("DISCORD_OWNER_ID", "42")
    from acelerado import youtube
    from acelerado.config import reload_settings

    reload_settings()
    called = {}

    def fake_complete(user_id, url):
        called["uid"] = user_id
        called["url"] = url

    monkeypatch.setattr(youtube, "complete_oauth_flow", fake_complete)

    cmd = _get_token_subcommand("renew-finish")
    interaction, _ = _make_token_interaction(user_id=42)
    await cmd.callback(interaction, redirect_url="http://localhost/?code=abc&state=xyz")

    assert called == {"uid": 42, "url": "http://localhost/?code=abc&state=xyz"}
    interaction.followup.send.assert_awaited_once()
    msg = interaction.followup.send.await_args.args[0]
    assert "renovado" in msg.lower()


# ---------------------------------------------------------------------------
# /update ok path (happy)
# ---------------------------------------------------------------------------


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
