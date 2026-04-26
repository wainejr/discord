"""Build Compiler Explorer (godbolt.org) ``clientstate`` URLs.

The clientstate format encodes a JSON payload as URL-safe base64. We
only emit single-session, single-compiler URLs — enough for
``/godbolt`` to drop the user into a ready-to-tweak playground.

Compiler IDs are Godbolt internals and may rotate over time. If a
link stops loading the right compiler, update :data:`COMPILERS`.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass

GODBOLT_BASE = "https://godbolt.org/clientstate/"


@dataclass(frozen=True)
class _Lang:
    display: str  # what users see in the slash command picker
    api_key: str  # Godbolt's "language" identifier
    compiler: str  # Godbolt's compiler id


# Edit here to add languages or update compilers. Compiler IDs come from
# Godbolt — go to https://godbolt.org, pick the language + compiler,
# inspect the URL: ``/api/compilers/<lang>`` lists the IDs. They rotate
# as new versions ship; if a link stops opening the right compiler,
# update the ``compiler`` field below.
LANGUAGES: dict[str, _Lang] = {
    "c": _Lang(display="C", api_key="c", compiler="cg132"),
    "c++": _Lang(display="C++", api_key="c++", compiler="g132"),
    "cpp": _Lang(display="C++ (alias cpp)", api_key="c++", compiler="g132"),
    "rust": _Lang(display="Rust", api_key="rust", compiler="r1830"),
    "zig": _Lang(display="Zig", api_key="zig", compiler="z0140"),
    "go": _Lang(display="Go", api_key="go", compiler="gccgo132"),
    "python": _Lang(display="Python", api_key="python", compiler="python313"),
    "javascript": _Lang(display="JavaScript", api_key="javascript", compiler="v8node2210"),
    "js": _Lang(display="JavaScript (alias js)", api_key="javascript", compiler="v8node2210"),
    "java": _Lang(display="Java", api_key="java", compiler="java2200"),
    "haskell": _Lang(display="Haskell", api_key="haskell", compiler="ghc984"),
    "odin": _Lang(display="Odin", api_key="odin", compiler="odintrunk"),
}


def supported_keys() -> list[str]:
    """Lowercase language keys accepted by :func:`build_clientstate_url`."""
    # Stable order for consistent error messages.
    return sorted(LANGUAGES)


def build_clientstate_url(language: str, source: str) -> str:
    """Return a ``godbolt.org/clientstate/<...>`` URL pre-loaded with the source.

    Raises ``ValueError`` if the language isn't in :data:`LANGUAGES`.
    """
    lang = LANGUAGES.get(language.lower())
    if lang is None:
        raise ValueError(f"linguagem não suportada: {language!r}")

    state = {
        "sessions": [
            {
                "id": 1,
                "language": lang.api_key,
                "source": source,
                "compilers": [{"id": lang.compiler, "options": ""}],
            }
        ]
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(state, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    return GODBOLT_BASE + encoded


def decode_clientstate_url(url: str) -> dict:
    """Inverse of :func:`build_clientstate_url`. Used by tests + debugging."""
    if not url.startswith(GODBOLT_BASE):
        raise ValueError(f"not a clientstate URL: {url}")
    encoded = url[len(GODBOLT_BASE) :]
    return json.loads(base64.urlsafe_b64decode(encoded).decode("utf-8"))
