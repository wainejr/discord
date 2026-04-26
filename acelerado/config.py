"""Layered runtime settings: ``config.json`` overrides ``.env`` overrides defaults.

The motivation (issue #30): IDs of channels/guild are *configuration*, not
secrets. Editing ``.env`` + restarting just to repoint the welcome channel
is friction we don't want. Secrets stay in ``.env`` (read by ``EnvCfg``);
runtime config moves to ``config.json``, editable via CLI (``acelerado
config``) and Discord slash commands (``/config``).

Resolution order (highest priority first):

1. ``config.json`` (atomic-written by :meth:`Settings.set`).
2. ``.env`` / process env (handled by ``EnvCfg`` via pydantic-settings).
3. Defaults declared on ``EnvCfg``.

Secrets — ``DISCORD_TOKEN``, ``YOUTUBE_API_KEY`` — are never written to
``config.json``. :meth:`Settings.set` rejects them; loader silently drops
them if they appear in the file (defense in depth).

Threading: the bot is single-threaded async; we don't lock. Atomic
``.tmp`` + replace keeps external readers (TUI, healthcheck) from seeing
half-written files, mirroring ``metrics.py``.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from acelerado.env import EnvCfg

logger = logging.getLogger(__name__)

CONFIG_PATH = Path("config.json")
ENV_FILE_PATH = Path(".env")

# Keys that MUST stay in environment / .env. Writing these to config.json
# would leak secrets into a file that's easy to accidentally commit.
SECRET_KEYS: frozenset[str] = frozenset({"DISCORD_TOKEN", "YOUTUBE_API_KEY"})

# Keys whose value is a Discord channel ID. Used by renderers (slash,
# CLI) to format the value as ``<#id>`` (clickable mention) instead of a
# bare int. Update this set when a new channel-shaped key is added.
CHANNEL_KEYS: frozenset[str] = frozenset(
    {
        "DISCORD_ANNOUNCE_CHANNEL_ID",
        "DISCORD_LOG_CHANNEL_ID",
        "DISCORD_WELCOME_CHANNEL_ID",
        "DISCORD_MODS_CHANNEL_ID",
        "DISCORD_REVIEW_CHANNEL_ID",
    }
)


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _read_env_file_keys(path: Path = ENV_FILE_PATH) -> set[str]:
    """Names defined in ``.env`` (best-effort parser, no quotes/expansion)."""
    if not path.exists():
        return set()
    keys: set[str] = set()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        name, _ = line.split("=", 1)
        keys.add(name.strip())
    return keys


class Settings:
    """Merged view of layered configuration.

    Construct once via :func:`get_settings`; mutating methods (:meth:`set`,
    :meth:`unset`) update the in-memory ``cfg`` *and* persist to disk so
    the next access — including from other modules holding a fresh
    ``get_settings()`` reference — sees the change immediately.
    """

    def __init__(self, path: Path = CONFIG_PATH) -> None:
        self.path = path
        self._overrides: dict[str, Any] = {}
        self._cfg: EnvCfg
        self._load_overrides()
        self._build_cfg()

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def _load_overrides(self) -> None:
        if not self.path.exists():
            self._overrides = {}
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(f"{self.path} unreadable ({exc}); ignoring overrides")
            self._overrides = {}
            return
        if not isinstance(data, dict):
            logger.warning(f"{self.path} must be a JSON object; ignoring overrides")
            self._overrides = {}
            return

        valid: dict[str, Any] = {}
        for key, value in data.items():
            if key not in EnvCfg.model_fields:
                logger.warning(f"Ignoring unknown {self.path.name} key: {key}")
                continue
            if key in SECRET_KEYS:
                logger.warning(f"Ignoring secret key {key} in {self.path.name}")
                continue
            valid[key] = value
        self._overrides = valid

    def _build_cfg(self) -> None:
        base = EnvCfg()
        if not self._overrides:
            self._cfg = base
            return
        data = base.model_dump()
        data.update(self._overrides)
        try:
            self._cfg = EnvCfg.model_validate(data)
        except ValidationError as exc:
            logger.warning(f"config.json overrides invalid ({exc}); ignoring")
            self._cfg = base

    # ------------------------------------------------------------------
    # Public read API
    # ------------------------------------------------------------------

    @property
    def cfg(self) -> EnvCfg:
        return self._cfg

    def reload(self) -> None:
        self._load_overrides()
        self._build_cfg()

    def all_keys(self) -> list[str]:
        return list(EnvCfg.model_fields.keys())

    def origin(self, key: str) -> str:
        """Return where ``key``'s effective value came from.

        One of: ``"config.json"``, ``"env"``, ``".env"``, ``"default"``.
        Raises ``KeyError`` for unknown keys.
        """
        if key not in EnvCfg.model_fields:
            raise KeyError(key)
        if key in self._overrides:
            return "config.json"
        if os.environ.get(key) is not None:
            return "env"
        if key in _read_env_file_keys(ENV_FILE_PATH):
            return ".env"
        return "default"

    def display_value(self, key: str) -> str:
        """Render ``key``'s value for human display, redacting secrets."""
        if key not in EnvCfg.model_fields:
            raise KeyError(key)
        value = getattr(self._cfg, key)
        if key in SECRET_KEYS:
            if isinstance(value, str) and len(value) >= 4:
                return f"***{value[-4:]}"
            return "***"
        return repr(value)

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def set(self, key: str, raw_value: Any) -> Any:
        """Persist ``key=raw_value`` to ``config.json`` after type-validation.

        Returns the typed/coerced value pydantic produced. Raises:

        - :class:`KeyError` for unknown keys,
        - :class:`PermissionError` for secret keys,
        - :class:`ValueError` on validation failure (wraps ``ValidationError``).
        """
        if key not in EnvCfg.model_fields:
            raise KeyError(f"Unknown config key: {key}")
        if key in SECRET_KEYS:
            raise PermissionError(f"{key} is a secret — set it in .env, not config.json")

        data = self._cfg.model_dump()
        data[key] = raw_value
        try:
            validated = EnvCfg.model_validate(data)
        except ValidationError as exc:
            raise ValueError(str(exc)) from exc

        coerced = getattr(validated, key)
        self._overrides[key] = coerced
        _atomic_write_json(self.path, self._overrides)
        self._cfg = validated
        return coerced

    def unset(self, key: str) -> None:
        """Remove ``key`` from ``config.json``; falls back to env / default.

        Raises :class:`KeyError` for unknown keys. No-op if the key has no
        override.
        """
        if key not in EnvCfg.model_fields:
            raise KeyError(key)
        if key not in self._overrides:
            return
        del self._overrides[key]
        if self._overrides:
            _atomic_write_json(self.path, self._overrides)
        else:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
        self._build_cfg()


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_singleton: Settings | None = None


def get_settings() -> Settings:
    global _singleton
    if _singleton is None:
        _singleton = Settings()
    return _singleton


def reload_settings() -> None:
    """Drop the singleton so the next ``get_settings()`` re-reads everything.

    Used by the CLI's ``config edit`` (after $EDITOR exits) and by the
    test fixtures so per-test env-var monkeypatching takes effect.
    """
    global _singleton
    _singleton = None
