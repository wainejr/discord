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
    assert "No cached token" in result.stdout
    assert "published.txt not initialized" in result.stdout


def test_status_with_token_and_published(chdir_tmp, token_future):
    (chdir_tmp / "published.txt").write_text("a\nb\nc\n")
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "3 published video(s)" in result.stdout
    # Token isn't expired, so we shouldn't see that banner
    assert "EXPIRED" not in result.stdout


def test_status_expired_token(chdir_tmp, write_token):
    from datetime import datetime, timedelta

    write_token(datetime.now(UTC) - timedelta(hours=1))
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "EXPIRED" in result.stdout


def test_log_level_option_accepted(chdir_tmp):
    result = runner.invoke(app, ["--log-level", "DEBUG", "status"])
    assert result.exit_code == 0


def test_invalid_log_level_fails(chdir_tmp):
    result = runner.invoke(app, ["--log-level", "XYZ", "status"])
    assert result.exit_code != 0
