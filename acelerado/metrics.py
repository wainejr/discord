"""Operational metrics: counters with timeline + atomic disk persistence.

Hooks fire from ``state`` (announce_video, check_members_apoiadores,
report_error, end of event_loop) and write to ``metrics.json``. Reads
happen from the TUI (`monitor`) and any external monitor that wants
a quick snapshot.

Atomicity: writes go to ``metrics.json.tmp`` then ``Path.replace`` —
readers (TUI tick, healthcheck script) never see a half-written file.

Threading note: the bot is single-threaded async; all increment paths
run in the asyncio event loop. We skip explicit locking on purpose.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

METRICS_PATH = Path("metrics.json")

# Timeline entries older than this are pruned on every increment so the
# JSON file doesn't grow forever. 30 days covers the windows we display
# (24h, 7d) with margin for ad-hoc inspection.
TIMELINE_RETENTION = timedelta(days=30)


class TimelineEntry(BaseModel):
    timestamp: datetime
    value: int = 1
    context: str = ""


class Metrics(BaseModel):
    videos_announced: list[TimelineEntry] = Field(default_factory=list)
    members_synced: list[TimelineEntry] = Field(default_factory=list)
    errors: list[TimelineEntry] = Field(default_factory=list)
    last_successful_tick: datetime | None = None


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def load(path: Path = METRICS_PATH) -> Metrics:
    if not path.exists():
        return Metrics()
    try:
        return Metrics.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(f"metrics.json corrupted ({exc}); starting fresh")
        return Metrics()


def _atomic_write(path: Path, data: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(data, encoding="utf-8")
    tmp.replace(path)


def save(m: Metrics, path: Path = METRICS_PATH) -> None:
    _atomic_write(path, m.model_dump_json(indent=2))


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------


def _prune(entries: list[TimelineEntry], cutoff: datetime) -> list[TimelineEntry]:
    return [e for e in entries if e.timestamp >= cutoff]


def increment(
    field_name: str,
    *,
    value: int = 1,
    context: str = "",
    path: Path = METRICS_PATH,
) -> None:
    """Append a timeline entry to ``field_name`` and persist."""
    if value <= 0:
        return  # nothing to record
    m = load(path)
    if not hasattr(m, field_name):
        raise AttributeError(f"Unknown metric field: {field_name}")

    entries: list[TimelineEntry] = getattr(m, field_name)
    now = datetime.now(UTC)
    entries.append(TimelineEntry(timestamp=now, value=value, context=context))
    setattr(m, field_name, _prune(entries, now - TIMELINE_RETENTION))
    save(m, path)


def mark_tick(path: Path = METRICS_PATH) -> None:
    """Stamp ``last_successful_tick`` with now-UTC and persist."""
    m = load(path)
    m.last_successful_tick = datetime.now(UTC)
    save(m, path)


# ---------------------------------------------------------------------------
# Aggregation helpers (used by TUI / healthcheck)
# ---------------------------------------------------------------------------


def window_total(entries: list[TimelineEntry], window: timedelta) -> int:
    cutoff = datetime.now(UTC) - window
    return sum(e.value for e in entries if e.timestamp >= cutoff)


def total(entries: list[TimelineEntry]) -> int:
    return sum(e.value for e in entries)
