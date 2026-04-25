"""Logging configuration.

Import-time side effects are avoided on purpose: modules should use
``logging.getLogger(__name__)`` and trust ``setup_logging`` to be called
once from the entrypoint (the typer root callback).
"""

import logging
from typing import Final

from rich.logging import RichHandler

_CONFIGURED: Final = "_acelerado_logging_configured"

# Third-party loggers we intentionally quiet unless the user opts into debug.
_NOISY_LOGGERS: Final = (
    "discord",
    "discord.gateway",
    "discord.http",
    "googleapiclient",
    "google_auth_httplib2",
    "urllib3",
)


def setup_logging(level: str | int = "INFO") -> None:
    """Configure root logging once. Safe to call multiple times."""
    if isinstance(level, str):
        level = level.upper()
    numeric_level = logging.getLevelName(level) if isinstance(level, str) else level
    if not isinstance(numeric_level, int):
        raise ValueError(f"Invalid log level: {level!r}")

    root = logging.getLogger()

    if getattr(root, _CONFIGURED, False):
        root.setLevel(min(numeric_level, logging.WARNING))
        logging.getLogger("acelerado").setLevel(numeric_level)
        return

    handler = RichHandler(
        rich_tracebacks=True,
        tracebacks_show_locals=False,
        show_path=False,
        markup=False,
        log_time_format="[%X]",
    )
    handler.setFormatter(logging.Formatter("%(name)s — %(message)s"))

    root.addHandler(handler)
    root.setLevel(logging.WARNING)
    logging.getLogger("acelerado").setLevel(numeric_level)

    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(
            logging.DEBUG if numeric_level <= logging.DEBUG else logging.WARNING
        )

    setattr(root, _CONFIGURED, True)
