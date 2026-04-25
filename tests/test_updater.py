"""Tests for ``acelerado.updater`` — subprocess fully mocked."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from acelerado import updater


def _proc(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    p = MagicMock()
    p.returncode = returncode
    p.stdout = stdout
    p.stderr = stderr
    return p


@pytest.fixture
def mock_run(monkeypatch: pytest.MonkeyPatch):
    """Replace ``subprocess.run`` with a queue of canned responses keyed by argv prefix.

    Each call dequeues the next matching response. Tests register responses by
    sequence — first git command, second git command, etc.
    """
    calls: list[list[str]] = []
    queue: list[MagicMock] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> MagicMock:
        calls.append(cmd)
        if not queue:
            raise AssertionError(f"Unexpected subprocess call: {cmd}")
        return queue.pop(0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    return type("MockRun", (), {"calls": calls, "queue": queue})


def test_check_updates_already_up_to_date(mock_run, tmp_path: Path):
    mock_run.queue.extend(
        [
            _proc(0),  # git fetch
            _proc(0, stdout="abc1234"),  # git rev-parse HEAD
            _proc(0, stdout="0"),  # git rev-list --count
        ]
    )
    result = updater.check_updates(repo=tmp_path)
    assert result.status == "clean"
    assert result.head == "abc1234"


def test_check_updates_with_pending_commits(mock_run, tmp_path: Path):
    mock_run.queue.extend(
        [
            _proc(0),
            _proc(0, stdout="abc1234"),
            _proc(0, stdout="3"),
            _proc(0, stdout="d2 commit two\nc1 commit one\nb0 commit zero"),  # git log
        ]
    )
    result = updater.check_updates(repo=tmp_path)
    assert result.status == "ok"
    assert result.head == "abc1234"
    assert result.short_head == "abc1234"
    assert len(result.commits) == 3


def test_check_updates_fetch_failure(mock_run, tmp_path: Path):
    mock_run.queue.append(_proc(1, stderr="network unreachable"))
    result = updater.check_updates(repo=tmp_path)
    assert result.status == "error"
    assert "network unreachable" in result.message


def test_apply_updates_clean_short_circuits(mock_run, tmp_path: Path):
    mock_run.queue.extend(
        [
            _proc(0),
            _proc(0, stdout="abc1234"),
            _proc(0, stdout="0"),
        ]
    )
    result = updater.apply_updates(repo=tmp_path)
    assert result.status == "clean"
    # Did not invoke git pull or uv sync
    cmds_run = [c[0] + " " + c[1] for c in mock_run.calls if len(c) >= 2]
    assert not any("pull" in c for c in cmds_run)


def test_apply_updates_happy_path(mock_run, tmp_path: Path):
    mock_run.queue.extend(
        [
            _proc(0),  # fetch
            _proc(0, stdout="oldhead"),  # rev-parse HEAD (pre)
            _proc(0, stdout="2"),  # rev-list --count
            _proc(0, stdout="d2 two\nc1 one"),  # log
            _proc(0),  # git pull --ff-only
            _proc(0),  # uv sync --frozen
            _proc(0, stdout="newheadhash"),  # rev-parse HEAD (post)
        ]
    )
    result = updater.apply_updates(repo=tmp_path)
    assert result.status == "ok"
    assert result.head == "newheadhash"
    assert len(result.commits) == 2


def test_apply_updates_conflict(mock_run, tmp_path: Path):
    mock_run.queue.extend(
        [
            _proc(0),
            _proc(0, stdout="oldhead"),
            _proc(0, stdout="1"),
            _proc(0, stdout="d2 two"),
            _proc(1, stderr="error: Your local changes would be overwritten"),
        ]
    )
    result = updater.apply_updates(repo=tmp_path)
    assert result.status == "conflict"
    assert "would be overwritten" in result.message


def test_apply_updates_uv_sync_fails(mock_run, tmp_path: Path):
    mock_run.queue.extend(
        [
            _proc(0),
            _proc(0, stdout="oldhead"),
            _proc(0, stdout="1"),
            _proc(0, stdout="d2 two"),
            _proc(0),  # pull ok
            _proc(1, stderr="resolution error"),  # uv sync fails
        ]
    )
    result = updater.apply_updates(repo=tmp_path)
    assert result.status == "error"
    assert "resolution error" in result.message
