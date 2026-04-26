"""Shared test fixtures.

Design notes
------------
- Every test runs in a fresh ``tmp_path`` (autouse ``chdir_tmp``) so the
  state/youtube modules can read/write ``published.txt`` and
  ``token.pickle`` without touching real files.
- ``clear_caches`` wipes ``@lru_cache``'d singletons between tests
  (env, youtube clients) so tests don't leak state into each other.
- ``env_setup`` populates required env vars + a placeholder token file
  so importing ``acelerado.env`` and ``acelerado.youtube`` never blocks
  on real credentials.
- ``fake_bot`` is a lightweight ``MagicMock`` shaped like ``commands.Bot``:
  only the attributes ``AceleradoState`` actually touches are stubbed.
  We avoid instantiating a real ``discord.Client`` — it would try to
  connect to the gateway.
"""

from __future__ import annotations

import json
import pickle
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Isolation: force-cwd + cache resets
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def chdir_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Every test runs from a throwaway directory."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture(autouse=True)
def clear_caches() -> None:
    """Reset lru_cache-backed singletons so tests don't leak state."""
    from acelerado import env as env_mod
    from acelerado import metrics as metrics_mod
    from acelerado import youtube as yt_mod

    env_mod.get_env.cache_clear()
    yt_mod._youtube.cache_clear()
    yt_mod.get_upload_playlist_id.cache_clear()
    metrics_mod.reset_cache()


@pytest.fixture(autouse=True)
def env_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Populate env vars expected by ``acelerado.env``."""
    monkeypatch.setenv("DISCORD_TOKEN", "test-discord-token")
    monkeypatch.setenv("DISCORD_GUILD_ID", "111")
    monkeypatch.setenv("DISCORD_ANNOUNCE_CHANNEL_ID", "222")
    monkeypatch.setenv("DISCORD_LOG_CHANNEL_ID", "333")
    monkeypatch.setenv("YOUTUBE_CHANNEL_ID", "UC_test_channel")
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-api-key")


# ---------------------------------------------------------------------------
# YouTube payload builders
# ---------------------------------------------------------------------------


def make_video(
    *,
    video_id: str = "vid123",
    title: str = "Example video",
    privacy_status: str = "public",
    upload_status: str = "processed",
    livestream: bool = False,
    members_only: bool = False,
    vertical: bool = False,
) -> dict[str, Any]:
    """Build a dict shaped like a ``youtube.videos().list`` item."""
    snippet: dict[str, Any] = {
        "publishedAt": "2026-04-24T00:00:00Z",
        "title": title,
        "channelTitle": "Waine - Dev do Desempenho",
        "resourceId": {"videoId": video_id, "kind": "youtube#video"},
        "tags": [],
    }
    if members_only:
        snippet["tags"].append("membros")

    video: dict[str, Any] = {
        "kind": "youtube#video",
        "id": video_id,
        "snippet": snippet,
        "status": {
            "uploadStatus": upload_status,
            "privacyStatus": privacy_status,
        },
        "fileDetails": {
            "videoStreams": [
                {
                    "widthPixels": 720 if vertical else 1920,
                    "heightPixels": 1280 if vertical else 1080,
                }
            ]
        },
    }
    if livestream:
        video["liveStreamingDetails"] = {
            "actualStartTime": "2026-04-24T00:00:00Z",
        }
    return video


def make_playlist_item(video_id: str = "vid123") -> dict[str, Any]:
    """Build a dict shaped like a ``youtube.playlistItems().list`` item."""
    return {
        "kind": "youtube#playlistItem",
        "snippet": {
            "publishedAt": "2026-04-24T00:00:00Z",
            "title": f"Title for {video_id}",
            "resourceId": {"kind": "youtube#video", "videoId": video_id},
        },
    }


@pytest.fixture
def sample_video() -> dict[str, Any]:
    return make_video()


@pytest.fixture
def make_video_fn():
    return make_video


@pytest.fixture
def make_playlist_item_fn():
    return make_playlist_item


# ---------------------------------------------------------------------------
# Fake Discord bot
# ---------------------------------------------------------------------------


def _make_member(name: str, member_id: int, roles: list[Any]) -> MagicMock:
    member = MagicMock(name=f"Member({name})")
    member.name = name
    member.id = member_id
    member.roles = roles
    member.add_roles = AsyncMock()
    return member


def _make_role(name: str, members: list[Any] | None = None) -> MagicMock:
    role = MagicMock(name=f"Role({name})")
    role.name = name
    role.members = members or []
    return role


def _make_channel(name: str) -> MagicMock:
    # spec the mock against TextChannel so ``isinstance(_, Messageable)``
    # checks in production code work as they would against a real channel.
    import discord

    channel = MagicMock(spec=discord.TextChannel)
    channel.name = name

    # ``channel.send`` returns a Message-like mock so callers can chain
    # ``.create_thread(...)`` (used by the auto-thread feature).
    sent_message = MagicMock(spec=discord.Message)
    sent_message.create_thread = AsyncMock()
    channel.send = AsyncMock(return_value=sent_message)
    return channel


@pytest.fixture
def fake_guild():
    """A guild with the two roles the bot looks for plus the chat channel."""
    apoiadores = _make_role("Registradores")
    yt_role = _make_role("YouTube Member (Nível 1)")
    other_role = _make_role("@everyone")

    announce = _make_channel("anuncios")
    log = _make_channel("logs")
    chat = _make_channel("chat-registradores")

    guild = MagicMock(name="Guild")
    guild.roles = [other_role, apoiadores, yt_role]
    guild.channels = [announce, log, chat]
    guild.members = []

    # Attach convenience handles so tests can poke at these easily.
    guild._apoiadores_role = apoiadores
    guild._yt_role = yt_role
    guild._announce = announce
    guild._log = log
    guild._chat = chat
    return guild


@pytest.fixture
def fake_bot(fake_guild):
    """Minimal stand-in for ``commands.Bot`` — only what AceleradoState uses."""
    bot = MagicMock(name="Bot")

    def _get_channel(channel_id: int):
        return {222: fake_guild._announce, 333: fake_guild._log}.get(channel_id)

    def _get_guild(guild_id: int):
        return fake_guild if guild_id == 111 else None

    bot.get_channel.side_effect = _get_channel
    bot.get_guild.side_effect = _get_guild
    return bot


# ---------------------------------------------------------------------------
# Token file helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def write_token(tmp_path: Path):
    """Write a fake ``token.pickle`` with the given expiry (aware UTC)."""

    def _write(expiry: datetime | None) -> Path:
        payload = {
            "token": "fake-access-token",
            "refresh_token": "fake-refresh-token",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "fake-client-id",
            "client_secret": "fake-client-secret",
            "scopes": ["https://www.googleapis.com/auth/youtube.readonly"],
        }
        if expiry is not None:
            # google-auth accepts ISO strings here; strip tz so we test the
            # module's normalization path.
            iso = expiry.astimezone(UTC).replace(tzinfo=None).isoformat()
            payload["expiry"] = iso
        path = tmp_path / "token.pickle"
        with path.open("wb") as f:
            pickle.dump(json.dumps(payload), f)
        return path

    return _write


@pytest.fixture
def token_future(write_token):
    """Token that expires well into the future."""
    return write_token(datetime.now(UTC) + timedelta(days=30))


@pytest.fixture
def token_soon(write_token):
    """Token that expires in an hour — triggers the warning path."""
    return write_token(datetime.now(UTC) + timedelta(hours=1))
