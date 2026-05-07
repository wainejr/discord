"""Tests for ``acelerado.cli`` using typer's CliRunner."""

from __future__ import annotations

from datetime import UTC

from typer.testing import CliRunner

from acelerado.cli import app

runner = CliRunner()


def test_help_exits_zero():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "acelerado" in result.stdout.lower()


def test_status_without_token_or_published(chdir_tmp):
    # Fresh cwd -> no token.pickle and no published.txt
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "No cached refresh token" in result.stdout
    assert "published.txt not initialized" in result.stdout


def test_status_with_token_and_published(chdir_tmp, token_future):
    (chdir_tmp / "published.txt").write_text("a\nb\nc\n")
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "3 published video(s)" in result.stdout
    # Bootstrap path: status fills in `now` for issuance, so a fresh
    # token should look like ~7 days remaining, not expired.
    assert "EXPIRED" not in result.stdout


def test_status_expired_refresh_token(chdir_tmp, token_future):
    """Refresh-token issuance well in the past -> banner shows EXPIRED."""
    from datetime import datetime, timedelta

    from acelerado import youtube

    youtube._record_refresh_issuance(now=datetime.now(UTC) - timedelta(days=10))
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "EXPIRED" in result.stdout


def test_log_level_option_accepted(chdir_tmp):
    result = runner.invoke(app, ["--log-level", "DEBUG", "status"])
    assert result.exit_code == 0


def test_invalid_log_level_fails(chdir_tmp):
    result = runner.invoke(app, ["--log-level", "XYZ", "status"])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# acelerado update
# ---------------------------------------------------------------------------


def test_update_command_clean(monkeypatch, chdir_tmp):
    from acelerado import updater

    monkeypatch.setattr(
        updater,
        "apply_updates",
        lambda repo=None: updater.UpdateResult(status="clean", head="abc1234"),
    )

    result = runner.invoke(app, ["update"])
    assert result.exit_code == 0
    assert "Nada pra atualizar" in result.stdout


def test_update_command_ok_exits_with_restart_code(monkeypatch, chdir_tmp):
    from acelerado import updater

    monkeypatch.setattr(
        updater,
        "apply_updates",
        lambda repo=None: updater.UpdateResult(
            status="ok",
            head="newhash1234567",
            commits=["d2 c1", "c1 c0"],
        ),
    )

    result = runner.invoke(app, ["update"])
    assert result.exit_code == updater.EXIT_RESTART
    assert "Atualizado" in result.stdout


def test_update_command_conflict_exits_one(monkeypatch, chdir_tmp):
    from acelerado import updater

    monkeypatch.setattr(
        updater,
        "apply_updates",
        lambda repo=None: updater.UpdateResult(status="conflict", message="bad merge"),
    )

    result = runner.invoke(app, ["update"])
    assert result.exit_code == 1
    assert "Conflito" in result.stdout


def test_update_command_error_exits_one(monkeypatch, chdir_tmp):
    from acelerado import updater

    monkeypatch.setattr(
        updater,
        "apply_updates",
        lambda repo=None: updater.UpdateResult(status="error", message="something blew up"),
    )

    result = runner.invoke(app, ["update"])
    assert result.exit_code == 1
    assert "Falhou" in result.stdout


# ---------------------------------------------------------------------------
# acelerado healthcheck
# ---------------------------------------------------------------------------


def test_healthcheck_missing_file_exits_one(chdir_tmp):
    result = runner.invoke(app, ["healthcheck"])
    assert result.exit_code == 1
    assert "stale" in result.stdout.lower()


def test_healthcheck_recent_tick_exits_zero(chdir_tmp):
    from datetime import UTC, datetime

    (chdir_tmp / "last_tick.txt").write_text(datetime.now(UTC).isoformat())
    result = runner.invoke(app, ["healthcheck"])
    assert result.exit_code == 0
    assert "ok" in result.stdout.lower()


def test_healthcheck_stale_exits_one(chdir_tmp):
    from datetime import UTC, datetime, timedelta

    stale = datetime.now(UTC) - timedelta(hours=2)
    (chdir_tmp / "last_tick.txt").write_text(stale.isoformat())
    result = runner.invoke(app, ["healthcheck", "--max-age", "60"])
    assert result.exit_code == 1
    assert "stale" in result.stdout.lower()


def test_healthcheck_corrupted_file_exits_one(chdir_tmp):
    (chdir_tmp / "last_tick.txt").write_text("not a date")
    result = runner.invoke(app, ["healthcheck"])
    assert result.exit_code == 1
    assert "corromp" in result.stdout.lower() or "stale" in result.stdout.lower()


# ---------------------------------------------------------------------------
# acelerado config
# ---------------------------------------------------------------------------


def test_config_list_shows_keys_and_origins(chdir_tmp):
    result = runner.invoke(app, ["config", "list"])
    assert result.exit_code == 0
    assert "ACELERADO_TICK_SECONDS" in result.stdout
    assert "DISCORD_TOKEN" in result.stdout


def test_config_list_redacts_secrets(chdir_tmp):
    result = runner.invoke(app, ["config", "list"])
    assert "test-discord-token" not in result.stdout


def test_config_get_known_key(chdir_tmp):
    result = runner.invoke(app, ["config", "get", "ACELERADO_TICK_SECONDS"])
    assert result.exit_code == 0
    assert "300" in result.stdout


def test_config_get_unknown_key_exits_one(chdir_tmp):
    result = runner.invoke(app, ["config", "get", "NOT_A_KEY"])
    assert result.exit_code == 1
    assert "unknown" in result.stdout.lower()


def test_config_set_persists_and_get_reflects_it(chdir_tmp):
    set_result = runner.invoke(app, ["config", "set", "ACELERADO_TICK_SECONDS", "120"])
    assert set_result.exit_code == 0, set_result.stdout
    assert "config.json" in set_result.stdout

    get_result = runner.invoke(app, ["config", "get", "ACELERADO_TICK_SECONDS"])
    assert get_result.exit_code == 0
    assert "120" in get_result.stdout
    assert "config.json" in get_result.stdout


def test_config_set_invalid_value_exits_one(chdir_tmp):
    result = runner.invoke(app, ["config", "set", "ACELERADO_TICK_SECONDS", "not-int"])
    assert result.exit_code == 1
    assert "validation" in result.stdout.lower()


def test_config_set_secret_blocked(chdir_tmp):
    result = runner.invoke(app, ["config", "set", "DISCORD_TOKEN", "leak"])
    assert result.exit_code == 1
    assert "secret" in result.stdout.lower()


def test_config_unset_returns_to_fallback(chdir_tmp):
    runner.invoke(app, ["config", "set", "ACELERADO_TICK_SECONDS", "120"])
    unset_result = runner.invoke(app, ["config", "unset", "ACELERADO_TICK_SECONDS"])
    assert unset_result.exit_code == 0
    get_result = runner.invoke(app, ["config", "get", "ACELERADO_TICK_SECONDS"])
    # Reverts to env (test fixture doesn't set it -> default 300)
    assert "300" in get_result.stdout


def test_config_unset_unknown_key_exits_one(chdir_tmp):
    result = runner.invoke(app, ["config", "unset", "NOT_A_KEY"])
    assert result.exit_code == 1
