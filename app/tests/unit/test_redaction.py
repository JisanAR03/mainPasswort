"""M1-02: the logging filter removes registered secrets (invariant I2)."""

from __future__ import annotations

import logging
import sys

import pytest
from personal_vault.core.redaction import MARKER, RedactionFilter

pytestmark = pytest.mark.unit


def _record(level: int, msg: str, args, exc_info=None) -> logging.LogRecord:
    return logging.LogRecord("pv", level, __file__, 1, msg, args, exc_info)


def test_message_redaction() -> None:
    redaction = RedactionFilter()
    redaction.add_secret("hunter2")
    record = _record(logging.INFO, "password is hunter2", ())
    assert redaction.filter(record) is True
    assert record.msg == f"password is {MARKER}"


def test_args_redaction() -> None:
    redaction = RedactionFilter()
    redaction.add_secret("hunter2")
    record = _record(logging.INFO, "tried %s for %s", ("hunter2", "alice"))
    redaction.filter(record)
    assert record.args == (MARKER, "alice")


def test_exception_text_redaction() -> None:
    redaction = RedactionFilter()
    redaction.add_secret("hunter2")
    try:
        raise ValueError("leaked hunter2 here")
    except ValueError:
        record = _record(logging.ERROR, "boom", (), sys.exc_info())
        redaction.filter(record)
        assert record.exc_info is not None
        assert "hunter2" not in str(record.exc_info[1])
        assert MARKER in str(record.exc_info[1])


def test_untouched_records_pass_through() -> None:
    redaction = RedactionFilter()
    record = _record(logging.INFO, "nothing secret", ())
    redaction.filter(record)
    assert record.msg == "nothing secret"


def test_empty_secret_is_ignored() -> None:
    redaction = RedactionFilter()
    redaction.add_secret("")
    record = _record(logging.INFO, "message", ())
    redaction.filter(record)
    assert record.msg == "message"
