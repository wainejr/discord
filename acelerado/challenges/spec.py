"""Schema for a challenge ``spec.json``.

Each challenge folder in ``wainejr/acelerado-desafios`` carries a
``spec.json`` that declares the primary metric, direction, hard caps,
and metadata about the input format. The bot only needs a thin slice of
that to render its announcement and ``/desafio`` reply, but the file
contents may grow over time — extra fields are preserved via pydantic's
``extra="allow"`` so we can round-trip them when needed.

Validation is intentionally permissive: an unknown ``primary_metric`` or
``direction`` doesn't reject the spec — it just falls back to generic
copy in the renderer. The bot announcing a malformed challenge is worse
than announcing a slightly-uglier one.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# YYYY-MM
_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class Spec(BaseModel):
    """Subset of ``spec.json`` the bot reads.

    Unknown fields are kept in :attr:`model_extra` so we don't lose
    things like ``image``/``psf``/``noise``/``bench`` that the harness
    cares about but the bot doesn't.
    """

    model_config = ConfigDict(extra="allow")

    name: str
    title: str
    month: str = Field(pattern=_MONTH_RE.pattern)
    primary_metric: str
    direction: str
    caps: dict[str, Any] = Field(default_factory=dict)

    @property
    def slug(self) -> str:
        """Folder name in the repo: ``<month>-<name>``."""
        return f"{self.month}-{self.name}"

    @property
    def site_url(self) -> str:
        """Public GitHub Pages URL for this challenge's page."""
        return f"https://wainejr.github.io/acelerado-desafios/desafios/{self.slug}/"


def load_spec(data: dict[str, Any]) -> Spec:
    """Validate ``data`` (already-parsed JSON) into a :class:`Spec`."""
    return Spec.model_validate(data)


def load_spec_file(path: Path) -> Spec:
    """Read + parse + validate a ``spec.json`` from disk."""
    return load_spec(json.loads(path.read_text(encoding="utf-8")))
