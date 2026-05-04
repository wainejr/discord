"""Schema + renderer for ``results.json``.

Each challenge ends with the maintainer committing a ``results.json``
to ``<slug>/`` in the desafios repo. Shape is deliberately loose —
metrics vary per challenge (PSNR for deblur, time for mandelbrot,
peak RSS for ext-sort, …) — so :class:`Entry.metrics` is an opaque
dict the renderer formats by name. Unknown metric keys fall through
to ``str(value)``.

The renderer produces a Markdown draft in PT-BR; it never posts on its
own. The draft flows through :class:`acelerado.review.EditableDraftView`
for human approval before going public.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# Metric direction is duplicated in spec.json; results.json carries it
# again for self-containment so the renderer doesn't need both files in
# memory just to know which way the ranking points.


class Entry(BaseModel):
    """One ranked submission. ``metrics`` mirrors per-run fields."""

    model_config = ConfigDict(extra="allow")

    rank: int
    user: str
    language: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)


class Disqualified(BaseModel):
    """One entry that failed validation or busted a cap."""

    model_config = ConfigDict(extra="allow")

    user: str
    reason: str


class Results(BaseModel):
    """Full results payload for one challenge.

    Extra fields at the top level are kept (``extra="allow"``) so the
    bot doesn't need to know about every future enrichment (timing
    breakdowns, hardware notes, …) just to render the post.
    """

    model_config = ConfigDict(extra="allow")

    slug: str
    primary_metric: str
    direction: str
    ranking: list[Entry] = Field(default_factory=list)
    disqualified: list[Disqualified] = Field(default_factory=list)


def load_results(data: dict[str, Any]) -> Results:
    return Results.model_validate(data)


def load_results_file(path: Path) -> Results:
    return load_results(json.loads(path.read_text(encoding="utf-8")))


# ---------------------------------------------------------------------------
# Metric value formatting
# ---------------------------------------------------------------------------


def _format_time_ms(value: Any) -> str:
    """Render a millisecond value as either ``ms`` or ``s`` depending on size."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if v >= 1000:
        return f"{v / 1000:.2f} s"
    return f"{v:.0f} ms"


def _format_bytes(value: Any) -> str:
    """Humanize a byte count with KB/MB suffixes."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if v >= 1_000_000:
        return f"{v / 1_000_000:.2f} MB"
    if v >= 1_000:
        return f"{v / 1_000:.1f} KB"
    return f"{v:.0f} B"


def _format_float(value: Any, suffix: str) -> str:
    try:
        return f"{float(value):.2f} {suffix}".rstrip()
    except (TypeError, ValueError):
        return str(value)


def format_metric_value(metric: str, value: Any) -> str:
    """Format ``value`` according to ``metric`` semantics.

    Unknown metrics fall through to ``str(value)`` — better than
    raising on a future metric we haven't taught the renderer about.
    """
    if metric in {"time_ms", "time_ms_per_image"}:
        rendered = _format_time_ms(value)
        if metric == "time_ms_per_image":
            return f"{rendered}/img"
        return rendered
    if metric in {"peak_rss_mb", "disk_write_mb"}:
        try:
            return f"{float(value):.0f} MB"
        except (TypeError, ValueError):
            return str(value)
    if metric in {"binary_size_bytes", "code_size_bytes"}:
        return _format_bytes(value)
    if metric == "psnr_mean_db":
        return _format_float(value, "dB")
    if metric == "quality":
        return _format_float(value, "")
    return str(value)


_PODIUM_EMOJI = {1: "🥇", 2: "🥈", 3: "🥉"}


def _entry_line(entry: Entry, primary: str) -> str:
    """Headline for one ranking entry — rank emoji + user + primary metric."""
    emoji = _PODIUM_EMOJI.get(entry.rank, "🔹")
    primary_value = entry.metrics.get(primary, "—")
    primary_str = format_metric_value(primary, primary_value)
    return f"{emoji} **{entry.rank}º:** @{entry.user} — **{primary_str}**"


def _entry_secondary_line(entry: Entry, primary: str) -> str | None:
    """Compact stats line shown below the headline.

    Includes secondary metrics (anything in ``entry.metrics`` other than
    the primary) plus the language if known. Returns ``None`` if there's
    nothing meaningful to show — caller skips the line entirely.
    """
    parts: list[str] = []
    for key, value in entry.metrics.items():
        if key == primary:
            continue
        parts.append(format_metric_value(key, value))
    if entry.language:
        parts.append(entry.language)
    return " · ".join(parts) if parts else None


def render_results_post(results: Results) -> str:
    """Render the full Markdown post for posting in the challenges channel."""
    lines = [f"## 🏁 Resultados — {results.slug}", ""]

    if not results.ranking:
        lines.append("_Sem submissões válidas neste desafio._")
    else:
        # Top 3 each get a headline + secondary line (when applicable);
        # ranks 4+ collapse into a one-liner per entry to keep posts
        # short on busy months.
        primary = results.primary_metric
        top = [e for e in results.ranking if e.rank <= 3]
        rest = [e for e in results.ranking if e.rank > 3]

        for entry in top:
            lines.append(_entry_line(entry, primary))
            secondary = _entry_secondary_line(entry, primary)
            if secondary:
                lines.append(f"   {secondary}")
            lines.append("")

        if rest:
            lines.append("**Demais participantes:**")
            for entry in rest:
                lines.append(f"• {_entry_line(entry, primary)}")
            lines.append("")

    if results.disqualified:
        lines.append("---")
        lines.append(f"**Desclassificados ({len(results.disqualified)}):**")
        for d in results.disqualified:
            lines.append(f"• @{d.user} — {d.reason}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
