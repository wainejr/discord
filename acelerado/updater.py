"""Self-update via ``git pull`` + ``uv sync``.

Used by both ``acelerado update`` (CLI) and ``/update`` (admin slash).
The functions here are pure orchestration over ``subprocess.run`` —
``check_updates`` and ``apply_updates`` return a structured ``UpdateResult``
that callers translate into Discord messages or terminal output.

Design contract: **never raise**. Every failure mode is encoded in
``UpdateResult.status`` so the consumers can react without try/except
gymnastics. This is part of the fail-proof contract for the bot.

Restart strategy: after a successful update, the process is expected to
exit with **EX_TEMPFAIL (75)** so the wrapper (e.g.
``while true; do uv run acelerado run; sleep 5; done``) restarts with
the new code. The CLI subcommand exits 75 directly; the slash command
schedules ``os._exit(75)`` a few seconds after sending the response.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

# Conventional exit code meaning "service unavailable; please retry" — used
# here as the signal to the supervising wrapper that the process exited
# cleanly because it wants to be restarted with new code.
EXIT_RESTART = 75


UpdateStatus = Literal["clean", "ok", "conflict", "error"]


@dataclass
class UpdateResult:
    status: UpdateStatus
    head: str = ""
    commits: list[str] = field(default_factory=list)
    message: str = ""

    @property
    def short_head(self) -> str:
        return self.head[:7] if self.head else ""


_DEFAULT_TIMEOUT = 60.0  # seconds


def _run(cmd: list[str], cwd: Path, timeout: float = _DEFAULT_TIMEOUT) -> tuple[int, str, str]:
    """Thin wrapper over subprocess.run that always captures stdout/stderr.

    A timeout prevents a hung ``git fetch`` (network blip, creds prompt) from
    pegging the bot — we'd rather fail fast and report ``error``. On timeout
    we synthesize ``returncode=124`` (the convention from coreutils
    ``timeout(1)``) so callers can tell it apart from a normal non-zero exit.
    """
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, cwd=str(cwd), timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {timeout:.0f}s"
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def check_updates(repo: Path | None = None) -> UpdateResult:
    """Fetch from origin and report whether the local branch is behind.

    Does **not** modify the working tree. Suitable for "is there an
    update?" probes.
    """
    repo = repo or Path.cwd()

    code, _, err = _run(["git", "fetch", "origin", "main"], cwd=repo)
    if code != 0:
        return UpdateResult(status="error", message=f"git fetch failed: {err}")

    code, head, _ = _run(["git", "rev-parse", "HEAD"], cwd=repo)
    if code != 0:
        return UpdateResult(status="error", message="git rev-parse HEAD failed")

    code, count_str, _ = _run(["git", "rev-list", "--count", "HEAD..origin/main"], cwd=repo)
    if code != 0:
        return UpdateResult(status="error", head=head, message="git rev-list failed")

    count = int(count_str or "0")
    if count == 0:
        return UpdateResult(status="clean", head=head, message="Already up to date")

    code, log_out, _ = _run(["git", "log", "HEAD..origin/main", "--oneline"], cwd=repo)
    commits = log_out.splitlines() if log_out else []
    return UpdateResult(
        status="ok",
        head=head,
        commits=commits,
        message=f"{count} new commit(s) on origin/main",
    )


def apply_updates(repo: Path | None = None) -> UpdateResult:
    """Pull latest commits and re-sync deps. Status reflects what happened."""
    repo = repo or Path.cwd()

    pre = check_updates(repo)
    if pre.status != "ok":
        return pre  # clean / error — nothing to apply

    code, _, err = _run(["git", "pull", "--ff-only", "origin", "main"], cwd=repo)
    if code != 0:
        return UpdateResult(
            status="conflict",
            head=pre.head,
            commits=pre.commits,
            message=err or "git pull failed (likely non-fast-forward)",
        )

    code, _, err = _run(["uv", "sync", "--frozen"], cwd=repo)
    if code != 0:
        return UpdateResult(
            status="error",
            head=pre.head,
            commits=pre.commits,
            message=f"uv sync failed: {err}",
        )

    code, head_after, _ = _run(["git", "rev-parse", "HEAD"], cwd=repo)
    return UpdateResult(
        status="ok",
        head=head_after if code == 0 else pre.head,
        commits=pre.commits,
        message="Updated",
    )
