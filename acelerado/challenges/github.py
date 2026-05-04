"""Async GitHub client for the challenges repo.

We talk to the public REST API (``api.github.com``). Anonymous calls are
limited to 60/h per IP; that's more than enough for a 5-minute tick, but
if ``GITHUB_TOKEN`` is set in the environment we use it for the larger
quota. The token is treated as a secret — never written to
``config.json``, only read at request time.

Errors are surfaced as :class:`GitHubError` so callers (the tick step)
can route them through :meth:`AceleradoState.report_error` without
caring whether the failure came from DNS, HTTP, or JSON.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

import httpx

from acelerado.challenges.spec import Spec, load_spec

logger = logging.getLogger(__name__)

API_BASE = "https://api.github.com"
DEFAULT_TIMEOUT = 10.0
USER_AGENT = "acelerado-bot (+https://github.com/wainejr/discord)"

# Folder names look like ``2026-05-deblur``. The leading ``YYYY-MM`` is
# the source of truth for "which challenge is current".
_SLUG_RE = re.compile(r"^(?P<month>\d{4}-(?:0[1-9]|1[0-2]))-[a-z0-9][a-z0-9-]*$")


class GitHubError(RuntimeError):
    """Wraps any failure talking to GitHub (network, HTTP, JSON shape)."""


def _headers(token: str | None) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": USER_AGENT,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _resolve_token(explicit: str | None) -> str | None:
    """Return the token to use, preferring the explicit arg over env."""
    if explicit:
        return explicit
    return os.environ.get("GITHUB_TOKEN") or None


async def _get_json(client: httpx.AsyncClient, url: str) -> Any:
    try:
        response = await client.get(url)
    except httpx.HTTPError as exc:
        raise GitHubError(f"network error fetching {url}: {exc}") from exc

    # Surface low rate-limit budgets so the operator notices before the
    # bot starts silently failing every tick.
    remaining = response.headers.get("X-RateLimit-Remaining")
    if remaining is not None and remaining.isdigit() and int(remaining) <= 5:
        logger.warning(f"GitHub rate limit low: {remaining} requests left")

    if response.status_code >= 400:
        raise GitHubError(f"{response.status_code} from {url}: {response.text[:200]}")

    try:
        return response.json()
    except ValueError as exc:
        raise GitHubError(f"invalid JSON from {url}: {exc}") from exc


def _client(token: str | None) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=API_BASE,
        headers=_headers(token),
        timeout=DEFAULT_TIMEOUT,
    )


async def list_challenge_slugs(repo: str, token: str | None = None) -> list[str]:
    """Return slugs of every challenge folder in the repo root.

    Folders that don't match ``YYYY-MM-<name>`` are skipped silently —
    the README, ``LICENSE``, ``SUBMISSION.md``, etc. live in the same
    place and we don't want to log noise about them every tick.
    """
    token = _resolve_token(token)
    async with _client(token) as client:
        entries = await _get_json(client, f"/repos/{repo}/contents")
    if not isinstance(entries, list):
        raise GitHubError(f"expected list from /contents, got {type(entries).__name__}")

    slugs: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("type") != "dir":
            continue
        name = entry.get("name")
        if isinstance(name, str) and _SLUG_RE.match(name):
            slugs.append(name)
    return sorted(slugs)


async def fetch_spec(repo: str, slug: str, token: str | None = None) -> Spec:
    """Fetch and validate ``<slug>/spec.json`` from the repo's default branch."""
    token = _resolve_token(token)
    # Use the raw endpoint — the contents API would return base64 we'd
    # then have to decode. Raw is plain JSON, smaller, and respects the
    # default branch automatically.
    url = f"https://raw.githubusercontent.com/{repo}/HEAD/{slug}/spec.json"
    async with httpx.AsyncClient(
        headers=_headers(token),
        timeout=DEFAULT_TIMEOUT,
    ) as client:
        try:
            response = await client.get(url)
        except httpx.HTTPError as exc:
            raise GitHubError(f"network error fetching {url}: {exc}") from exc
        if response.status_code >= 400:
            raise GitHubError(f"{response.status_code} from {url}: {response.text[:200]}")
        try:
            data = response.json()
        except ValueError as exc:
            raise GitHubError(f"invalid JSON from {url}: {exc}") from exc
    return load_spec(data)


def slug_month(slug: str) -> str | None:
    """Extract the ``YYYY-MM`` prefix from a slug, or ``None`` if unparseable."""
    match = _SLUG_RE.match(slug)
    return match.group("month") if match else None


async def find_current_spec(
    repo: str,
    month: str,
    token: str | None = None,
) -> Spec | None:
    """Locate and fetch the spec for the challenge whose slug matches ``month``.

    Returns ``None`` if no folder for that month exists yet — that's a
    normal state on the 1st of the month before publication.
    """
    slugs = await list_challenge_slugs(repo, token=token)
    for slug in slugs:
        if slug_month(slug) == month:
            return await fetch_spec(repo, slug, token=token)
    return None
