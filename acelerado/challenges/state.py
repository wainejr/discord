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

    @property
    def raw(self) -> dict[str, Any]:
        """Read-only snapshot — for diagnostics / future phases."""
        return dict(self._data)
