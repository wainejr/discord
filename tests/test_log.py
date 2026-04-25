"""Tests for ``acelerado.log`` — setup_logging idempotence + level gating."""

from __future__ import annotations

import logging

import pytest

from acelerado.log import setup_logging


@pytest.fixture(autouse=True)
def _reset_logging():
    """Nuke any handlers attached by previous tests so each case starts clean."""
    root = logging.getLogger()
    saved = list(root.handlers)
    saved_level = root.level
    was_configured = getattr(root, "_acelerado_logging_configured", False)
    root.handlers.clear()
    if hasattr(root, "_acelerado_logging_configured"):
        delattr(root, "_acelerado_logging_configured")
    yield
    root.handlers.clear()
    for h in saved:
        root.addHandler(h)
    root.setLevel(saved_level)
    if was_configured:
        root._acelerado_logging_configured = True  # type: ignore[attr-defined]


def _acelerado_handler_count() -> int:
    from rich.logging import RichHandler

    return sum(1 for h in logging.getLogger().handlers if isinstance(h, RichHandler))


def test_setup_logging_attaches_rich_handler():
    setup_logging("INFO")
    assert _acelerado_handler_count() == 1


def test_setup_logging_is_idempotent():
    setup_logging("INFO")
    setup_logging("DEBUG")
    setup_logging("WARNING")
    assert _acelerado_handler_count() == 1, "must not attach duplicate handlers"


def test_setup_logging_sets_acelerado_level():
    setup_logging("DEBUG")
    assert logging.getLogger("acelerado").level == logging.DEBUG
    setup_logging("WARNING")
    assert logging.getLogger("acelerado").level == logging.WARNING


def test_third_party_loggers_are_muted_at_info():
    setup_logging("INFO")
    assert logging.getLogger("discord").level == logging.WARNING
    assert logging.getLogger("googleapiclient").level == logging.WARNING
    assert logging.getLogger("urllib3").level == logging.WARNING


def test_third_party_loggers_follow_debug():
    setup_logging("DEBUG")
    assert logging.getLogger("discord").level == logging.DEBUG


def test_setup_logging_rejects_invalid_level():
    with pytest.raises(ValueError, match="Invalid log level"):
        setup_logging("NOT_A_LEVEL")


def test_numeric_level_accepted():
    setup_logging(logging.DEBUG)
    assert logging.getLogger("acelerado").level == logging.DEBUG
