"""Tests for ``acelerado.challenges.state``."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from acelerado.challenges.state import ChallengesState


def test_fresh_state_has_no_announcements(tmp_path: Path):
    state = ChallengesState(tmp_path / "state.json")
    assert state.is_announced("2026-05-deblur") is False


def test_mark_announced_persists_to_disk(tmp_path: Path):
    path = tmp_path / "state.json"
    state = ChallengesState(path)
    state.mark_announced("2026-05-deblur")

    assert state.is_announced("2026-05-deblur") is True
    on_disk = json.loads(path.read_text())
    assert on_disk["announced"] == ["2026-05-deblur"]


def test_mark_announced_is_idempotent(tmp_path: Path):
    path = tmp_path / "state.json"
    state = ChallengesState(path)
    state.mark_announced("2026-05-deblur")
    state.mark_announced("2026-05-deblur")

    on_disk = json.loads(path.read_text())
    assert on_disk["announced"] == ["2026-05-deblur"]


def test_state_round_trips_through_disk(tmp_path: Path):
    path = tmp_path / "state.json"
    a = ChallengesState(path)
    a.mark_announced("2026-05-deblur")

    b = ChallengesState(path)
    assert b.is_announced("2026-05-deblur") is True


def test_corrupt_file_starts_fresh(tmp_path: Path):
    path = tmp_path / "state.json"
    path.write_text("{not json")
    state = ChallengesState(path)
    assert state.is_announced("anything") is False
    # Should still be writable after recovering.
    state.mark_announced("2026-05-deblur")
    assert state.is_announced("2026-05-deblur") is True


def test_non_object_root_starts_fresh(tmp_path: Path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps([1, 2, 3]))
    state = ChallengesState(path)
    assert state.raw == {}


# ---------------------------------------------------------------------------
# Phase 3 — results posted/dismissed + reminder rate-limit
# ---------------------------------------------------------------------------


def test_mark_results_posted_persists(tmp_path: Path):
    path = tmp_path / "state.json"
    state = ChallengesState(path)
    state.mark_results_posted("2026-05-deblur")

    assert state.is_results_posted("2026-05-deblur")
    on_disk = json.loads(path.read_text())
    assert on_disk["results_posted"] == ["2026-05-deblur"]


def test_mark_results_dismissed_persists(tmp_path: Path):
    path = tmp_path / "state.json"
    state = ChallengesState(path)
    state.mark_results_dismissed("2026-04-mandelbrot")

    assert state.is_results_dismissed("2026-04-mandelbrot")
    on_disk = json.loads(path.read_text())
    assert on_disk["results_dismissed"] == ["2026-04-mandelbrot"]


def test_mark_idempotent(tmp_path: Path):
    state = ChallengesState(tmp_path / "state.json")
    state.mark_results_posted("x")
    state.mark_results_posted("x")
    state.mark_results_dismissed("y")
    state.mark_results_dismissed("y")
    assert state._list("results_posted") == ["x"]
    assert state._list("results_dismissed") == ["y"]


def test_should_remind_true_when_never_reminded(tmp_path: Path):
    state = ChallengesState(tmp_path / "state.json")
    assert state.should_remind("2026-05-deblur") is True


def test_should_remind_false_when_posted(tmp_path: Path):
    state = ChallengesState(tmp_path / "state.json")
    state.mark_results_posted("2026-05-deblur")
    assert state.should_remind("2026-05-deblur") is False


def test_should_remind_false_when_dismissed(tmp_path: Path):
    state = ChallengesState(tmp_path / "state.json")
    state.mark_results_dismissed("2026-05-deblur")
    assert state.should_remind("2026-05-deblur") is False


def test_should_remind_respects_cooldown(tmp_path: Path):
    state = ChallengesState(tmp_path / "state.json")
    state.mark_reminded("2026-05-deblur")
    # Default cooldown is 24h — fresh reminder shouldn't fire.
    assert state.should_remind("2026-05-deblur") is False


def test_should_remind_after_cooldown_elapsed(tmp_path: Path):
    state = ChallengesState(tmp_path / "state.json")
    # Backdate the timestamp by 25h to simulate elapsed cooldown.
    past = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
    state._data["last_remind_at"] = {"2026-05-deblur": past}
    state._flush()
    assert state.should_remind("2026-05-deblur") is True


def test_should_remind_handles_corrupt_timestamp(tmp_path: Path):
    state = ChallengesState(tmp_path / "state.json")
    state._data["last_remind_at"] = {"2026-05-deblur": "not-a-date"}
    # Garbled value should NOT mute the reminder forever — we just ignore it.
    assert state.should_remind("2026-05-deblur") is True


def test_mark_reminded_persists(tmp_path: Path):
    path = tmp_path / "state.json"
    state = ChallengesState(path)
    state.mark_reminded("2026-05-deblur")

    on_disk = json.loads(path.read_text())
    assert "2026-05-deblur" in on_disk["last_remind_at"]
    # Should round-trip into a parseable datetime.
    parsed = datetime.fromisoformat(on_disk["last_remind_at"]["2026-05-deblur"])
    assert parsed.tzinfo is not None
