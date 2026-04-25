"""Tests for ``acelerado.env`` (pydantic-settings)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from acelerado import env as env_mod


def test_env_loads_from_monkeypatched_vars():
    cfg = env_mod.get_env()
    assert cfg.DISCORD_TOKEN == "test-discord-token"
    assert cfg.DISCORD_GUILD_ID == 111
    assert cfg.DISCORD_ANNOUNCE_CHANNEL_ID == 222
    assert cfg.DISCORD_LOG_CHANNEL_ID == 333
    assert cfg.YOUTUBE_CHANNEL_ID == "UC_test_channel"
    assert cfg.YOUTUBE_API_KEY == "test-api-key"


def test_env_missing_required_raises(monkeypatch):
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)
    env_mod.get_env.cache_clear()
    with pytest.raises(ValidationError):
        env_mod.get_env()


def test_env_is_cached():
    env_mod.get_env.cache_clear()
    first = env_mod.get_env()
    second = env_mod.get_env()
    assert first is second


def test_tick_seconds_default_is_300():
    cfg = env_mod.get_env()
    assert cfg.ACELERADO_TICK_SECONDS == 300


def test_tick_seconds_honors_env_var(monkeypatch):
    monkeypatch.setenv("ACELERADO_TICK_SECONDS", "42")
    env_mod.get_env.cache_clear()
    assert env_mod.get_env().ACELERADO_TICK_SECONDS == 42
