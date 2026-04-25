"""Tests for ``acelerado.metrics``."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from acelerado import metrics


def test_load_missing_file_returns_empty(tmp_path: Path):
    m = metrics.load(tmp_path / "missing.json")
    assert m.videos_announced == []
    assert m.last_successful_tick is None


def test_save_and_load_roundtrip(tmp_path: Path):
    p = tmp_path / "metrics.json"
    m = metrics.Metrics(
        videos_announced=[
            metrics.TimelineEntry(timestamp=datetime.now(UTC), value=1, context="abc")
        ],
        last_successful_tick=datetime.now(UTC),
    )
    metrics.save(m, p)
    reloaded = metrics.load(p)
    assert len(reloaded.videos_announced) == 1
    assert reloaded.videos_announced[0].context == "abc"
    assert reloaded.last_successful_tick is not None


def test_increment_appends_and_persists(tmp_path: Path):
    p = tmp_path / "metrics.json"
    metrics.increment("videos_announced", context="vid1", path=p)
    metrics.increment("videos_announced", context="vid2", path=p)

    m = metrics.load(p)
    assert len(m.videos_announced) == 2
    assert m.videos_announced[0].context == "vid1"
    assert m.videos_announced[1].context == "vid2"


def test_increment_zero_value_is_noop(tmp_path: Path):
    p = tmp_path / "metrics.json"
    metrics.increment("members_synced", value=0, path=p)
    assert metrics.load(p).members_synced == []


def test_increment_unknown_field_raises(tmp_path: Path):
    import pytest

    with pytest.raises(AttributeError):
        metrics.increment("not_a_field", path=tmp_path / "x.json")


def test_increment_prunes_old_entries(tmp_path: Path, monkeypatch):
    p = tmp_path / "metrics.json"
    # Seed with an old entry directly via load+save
    old = metrics.Metrics(
        videos_announced=[
            metrics.TimelineEntry(
                timestamp=datetime.now(UTC) - timedelta(days=60), value=1, context="old"
            )
        ]
    )
    metrics.save(old, p)

    metrics.increment("videos_announced", context="fresh", path=p)
    m = metrics.load(p)
    contexts = [e.context for e in m.videos_announced]
    assert "old" not in contexts
    assert "fresh" in contexts


def test_mark_tick_sets_timestamp(tmp_path: Path):
    p = tmp_path / "metrics.json"
    metrics.mark_tick(p)
    m = metrics.load(p)
    assert m.last_successful_tick is not None
    assert m.last_successful_tick.tzinfo is not None  # aware UTC


def test_window_total_filters_by_age(tmp_path: Path):
    now = datetime.now(UTC)
    entries = [
        metrics.TimelineEntry(timestamp=now - timedelta(hours=1), value=1),
        metrics.TimelineEntry(timestamp=now - timedelta(hours=12), value=2),
        metrics.TimelineEntry(timestamp=now - timedelta(days=2), value=4),
    ]
    assert metrics.window_total(entries, timedelta(hours=24)) == 3
    assert metrics.window_total(entries, timedelta(days=3)) == 7


def test_load_corrupted_file_returns_empty(tmp_path: Path):
    p = tmp_path / "metrics.json"
    p.write_text("{not valid json")
    m = metrics.load(p)
    assert m.videos_announced == []  # fresh start
