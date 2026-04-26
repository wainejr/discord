"""Tests for ``acelerado.slash`` — registration + response shape.

We avoid instantiating the full ``AceleradoBot`` (which would try to
connect to the gateway). A bare ``discord.Client`` is fine — its
constructor doesn't open any sockets.
"""

from __future__ import annotations

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
