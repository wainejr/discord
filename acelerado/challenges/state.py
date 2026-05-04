"""Persistent state for the challenge tick.

A single JSON file (``challenges_state.json``) tracks what we've already
announced so the tick is idempotent across bot restarts. Phase 1 only
needs the announcement marker; later phases will tack on submission
counts and the results-posted flag.

Atomic write follows the same pattern as :mod:`acelerado.config` —
``.tmp`` + ``replace`` so external readers (TUI, healthcheck) never see
a half-written file.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CHALLENGES_STATE_PATH = Path("challenges_state.json")


class ChallengesState:
    """In-memory view backed by ``challenges_state.json``.

    The file is the source of truth — every mutation flushes
    immediately. This keeps the surface tiny: callers don't need to
    remember to ``save()``.
    """

    def __init__(self, path: Path = CHALLENGES_STATE_PATH) -> None:
        self.path = path
        self._data: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(f"{self.path} unreadable ({exc}); starting fresh")
            return {}
        if not isinstance(data, dict):
            logger.warning(f"{self.path} must be a JSON object; starting fresh")
            return {}
        return data

    def _flush(self) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._data, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)

    # ------------------------------------------------------------------
    # Announce idempotency — keyed by the challenge slug, not the month,
    # so a typo-fix that renames the folder mid-month re-announces.
    # ------------------------------------------------------------------

    def is_announced(self, slug: str) -> bool:
        announced = self._data.get("announced", [])
        return isinstance(announced, list) and slug in announced

    def mark_announced(self, slug: str) -> None:
        announced = self._data.setdefault("announced", [])
        if not isinstance(announced, list):
            announced = []
            self._data["announced"] = announced
        if slug in announced:
            return
        announced.append(slug)
        self._flush()

    # ------------------------------------------------------------------
    # Results posting (Phase 3) — manual via /desafio resultados.
    # The state tracks slugs already drafted (so we don't re-cobrar
    # them) and slugs explicitly skipped (operator told us to stop).
    # ``last_remind_at`` rate-limits the reminder step to 1×/24h per
    # slug regardless of tick frequency.
    # ------------------------------------------------------------------

    def _list(self, key: str) -> list[str]:
        value = self._data.get(key, [])
        return value if isinstance(value, list) else []

    def is_results_posted(self, slug: str) -> bool:
        return slug in self._list("results_posted")

    def mark_results_posted(self, slug: str) -> None:
        posted = self._data.setdefault("results_posted", [])
        if not isinstance(posted, list):
            posted = []
            self._data["results_posted"] = posted
        if slug in posted:
            return
        posted.append(slug)
        self._flush()

    def is_results_dismissed(self, slug: str) -> bool:
        return slug in self._list("results_dismissed")

    def mark_results_dismissed(self, slug: str) -> None:
        dismissed = self._data.setdefault("results_dismissed", [])
        if not isinstance(dismissed, list):
            dismissed = []
            self._data["results_dismissed"] = dismissed
        if slug in dismissed:
            return
        dismissed.append(slug)
        self._flush()

    def should_remind(self, slug: str, *, cooldown: timedelta = timedelta(hours=24)) -> bool:
        """Return ``True`` iff we haven't reminded about ``slug`` recently.

        Posted/dismissed slugs short-circuit to ``False`` regardless of
        the cooldown — once acted on, the reminder is done forever.
        """
        if self.is_results_posted(slug) or self.is_results_dismissed(slug):
            return False
        last = (
            self._data.get("last_remind_at", {}).get(slug)
            if isinstance(self._data.get("last_remind_at"), dict)
            else None
        )
        if last is None:
            return True
        try:
            last_dt = datetime.fromisoformat(last)
        except (TypeError, ValueError):
            return True
        return datetime.now(UTC) - last_dt >= cooldown

    def mark_reminded(self, slug: str) -> None:
        bucket = self._data.setdefault("last_remind_at", {})
        if not isinstance(bucket, dict):
            bucket = {}
            self._data["last_remind_at"] = bucket
        bucket[slug] = datetime.now(UTC).isoformat()
        self._flush()

    @property
    def raw(self) -> dict[str, Any]:
        """Read-only snapshot — for diagnostics / future phases."""
        return dict(self._data)
