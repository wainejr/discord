"""Tests for ``acelerado.config`` — layered Settings + persistence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from acelerado import config as config_mod
from acelerado.config import CONFIG_PATH, SECRET_KEYS, Settings


def test_defaults_when_no_config_json() -> None:
    s = Settings()
    assert s.cfg.ACELERADO_TICK_SECONDS == 300
    assert s.cfg.ACELERADO_AUTO_THREAD is True
    assert s.origin("ACELERADO_TICK_SECONDS") == "default"


def test_env_var_takes_precedence_over_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACELERADO_TICK_SECONDS", "42")
    s = Settings()
    assert s.cfg.ACELERADO_TICK_SECONDS == 42
    assert s.origin("ACELERADO_TICK_SECONDS") == "env"


def test_config_json_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACELERADO_TICK_SECONDS", "42")
    CONFIG_PATH.write_text(json.dumps({"ACELERADO_TICK_SECONDS": 99}), encoding="utf-8")
    s = Settings()
    assert s.cfg.ACELERADO_TICK_SECONDS == 99
    assert s.origin("ACELERADO_TICK_SECONDS") == "config.json"


def test_set_persists_and_returns_coerced() -> None:
    s = Settings()
    coerced = s.set("ACELERADO_TICK_SECONDS", "120")
    assert coerced == 120  # str coerced to int via pydantic
    assert s.cfg.ACELERADO_TICK_SECONDS == 120
    on_disk = json.loads(CONFIG_PATH.read_text())
    assert on_disk == {"ACELERADO_TICK_SECONDS": 120}


def test_set_invalid_value_raises_valueerror() -> None:
    s = Settings()
    with pytest.raises(ValueError):
        s.set("ACELERADO_TICK_SECONDS", "not-an-int")
    # cfg unchanged, no file written
    assert s.cfg.ACELERADO_TICK_SECONDS == 300
    assert not CONFIG_PATH.exists()


def test_set_unknown_key_raises_keyerror() -> None:
    s = Settings()
    with pytest.raises(KeyError):
        s.set("NOT_A_REAL_KEY", "x")


def test_set_secret_raises_permissionerror() -> None:
    s = Settings()
    for secret in SECRET_KEYS:
        with pytest.raises(PermissionError):
            s.set(secret, "leaked")
    assert not CONFIG_PATH.exists()


def test_unset_removes_from_disk_and_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACELERADO_TICK_SECONDS", "42")
    s = Settings()
    s.set("ACELERADO_TICK_SECONDS", 99)
    assert s.cfg.ACELERADO_TICK_SECONDS == 99
    s.unset("ACELERADO_TICK_SECONDS")
    assert s.cfg.ACELERADO_TICK_SECONDS == 42
    assert not CONFIG_PATH.exists()  # last override removed -> file deleted
    assert s.origin("ACELERADO_TICK_SECONDS") == "env"


def test_unset_missing_key_is_noop() -> None:
    s = Settings()
    s.unset("ACELERADO_TICK_SECONDS")  # no error, no file
    assert not CONFIG_PATH.exists()


def test_unset_unknown_key_raises_keyerror() -> None:
    s = Settings()
    with pytest.raises(KeyError):
        s.unset("NOT_A_REAL_KEY")


def test_corrupted_config_json_is_ignored(caplog: pytest.LogCaptureFixture) -> None:
    CONFIG_PATH.write_text("{not valid json", encoding="utf-8")
    s = Settings()
    assert s.cfg.ACELERADO_TICK_SECONDS == 300  # default
    assert "unreadable" in caplog.text.lower() or "invalid" in caplog.text.lower()


def test_secret_key_in_config_json_is_dropped(caplog: pytest.LogCaptureFixture) -> None:
    CONFIG_PATH.write_text(
        json.dumps({"DISCORD_TOKEN": "leaked", "ACELERADO_TICK_SECONDS": 60}),
        encoding="utf-8",
    )
    s = Settings()
    # Token still comes from env, not from config.json
    assert s.cfg.DISCORD_TOKEN == "test-discord-token"
    assert s.cfg.ACELERADO_TICK_SECONDS == 60
    assert "secret" in caplog.text.lower()


def test_unknown_key_in_config_json_is_dropped(caplog: pytest.LogCaptureFixture) -> None:
    CONFIG_PATH.write_text(
        json.dumps({"FROM_FUTURE_VERSION": "x", "ACELERADO_TICK_SECONDS": 77}),
        encoding="utf-8",
    )
    s = Settings()
    assert s.cfg.ACELERADO_TICK_SECONDS == 77
    assert "unknown" in caplog.text.lower()


def test_atomic_write_no_tmp_left_behind() -> None:
    s = Settings()
    s.set("ACELERADO_TICK_SECONDS", 60)
    assert CONFIG_PATH.exists()
    assert not Path("config.json.tmp").exists()


def test_reload_picks_up_external_edit(monkeypatch: pytest.MonkeyPatch) -> None:
    s = Settings()
    assert s.cfg.ACELERADO_TICK_SECONDS == 300
    CONFIG_PATH.write_text(json.dumps({"ACELERADO_TICK_SECONDS": 12}), encoding="utf-8")
    s.reload()
    assert s.cfg.ACELERADO_TICK_SECONDS == 12


def test_singleton_get_settings_returns_same_instance() -> None:
    a = config_mod.get_settings()
    b = config_mod.get_settings()
    assert a is b


def test_reload_settings_drops_singleton() -> None:
    a = config_mod.get_settings()
    config_mod.reload_settings()
    b = config_mod.get_settings()
    assert a is not b


def test_display_value_redacts_secrets() -> None:
    s = Settings()
    rendered = s.display_value("DISCORD_TOKEN")
    assert "test-discord-token" not in rendered
    assert rendered.startswith("***")


def test_display_value_for_non_secret_is_repr() -> None:
    s = Settings()
    assert s.display_value("ACELERADO_TICK_SECONDS") == "300"


def test_origin_distinguishes_env_file_vs_process_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A key only in .env (not process env) reports origin=='.env'."""
    # Drop the test-fixture process-env override for one var, then write
    # it into a .env file that EnvCfg will pick up.
    monkeypatch.delenv("ACELERADO_TICK_SECONDS", raising=False)
    Path(".env").write_text(
        # Required vars + the one we care about.
        "DISCORD_TOKEN=test-discord-token\n"
        "DISCORD_GUILD_ID=111\n"
        "DISCORD_ANNOUNCE_CHANNEL_ID=222\n"
        "DISCORD_LOG_CHANNEL_ID=333\n"
        "YOUTUBE_CHANNEL_ID=UC_test_channel\n"
        "YOUTUBE_API_KEY=test-api-key\n"
        "ACELERADO_TICK_SECONDS=77\n",
        encoding="utf-8",
    )
    # Required vars must NOT be in process env or pydantic-settings will
    # report "env" instead of ".env"; clear them.
    for k in (
        "DISCORD_TOKEN",
        "DISCORD_GUILD_ID",
        "DISCORD_ANNOUNCE_CHANNEL_ID",
        "DISCORD_LOG_CHANNEL_ID",
        "YOUTUBE_CHANNEL_ID",
        "YOUTUBE_API_KEY",
    ):
        monkeypatch.delenv(k, raising=False)
    s = Settings()
    assert s.cfg.ACELERADO_TICK_SECONDS == 77
    assert s.origin("ACELERADO_TICK_SECONDS") == ".env"
