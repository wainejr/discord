"""File-backed unique-line set.

``published.txt`` and ``live_reminders.txt`` both encode "set of IDs we've
already done something about, one per line." This wraps the read / contains
/ append-if-new pattern so the call sites stop re-implementing the
trailing-newline dance.
"""

from __future__ import annotations

from pathlib import Path


class LineSetStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def read_all(self) -> list[str]:
        if not self.path.exists():
            return []
        return [ln.strip() for ln in self.path.read_text().splitlines() if ln.strip()]

    def as_set(self) -> set[str]:
        return set(self.read_all())

    def __contains__(self, line: str) -> bool:
        return line in self.as_set()

    def add(self, line: str) -> bool:
        """Append ``line`` if not already present. Returns True if added."""
        if line in self.as_set():
            return False
        existing = self.path.read_text() if self.path.exists() else ""
        sep = "" if not existing or existing.endswith("\n") else "\n"
        with self.path.open("a") as f:
            f.write(f"{sep}{line}\n")
        return True
