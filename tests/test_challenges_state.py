"""Tests for ``acelerado.challenges.state``."""

from __future__ import annotations

import json
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
