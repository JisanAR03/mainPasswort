"""Logging filter that removes registered secrets from log records ([S]).

Anything that must never reach a log file gets registered here; the filter
rewrites the message, its arguments and the exception text before any handler
sees them (invariant I2).
"""

from __future__ import annotations

import logging

MARKER = "[REDACTED]"


class RedactionFilter(logging.Filter):
    """Replaces every registered secret with MARKER in any log record."""

    def __init__(self, name: str = "") -> None:
        super().__init__(name)
        self._secrets: set[str] = set()

    def add_secret(self, value: str) -> None:
        if value:
            self._secrets.add(value)

    def _redact(self, text: str) -> str:
        for secret in self._secrets:
            text = text.replace(secret, MARKER)
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self._redact(str(record.msg))
        args = record.args
        if args:
            record.args = tuple(self._redact(arg) if isinstance(arg, str) else arg for arg in args)
        if record.exc_info and record.exc_info[1] is not None:
            exc_type, exc_value, tb = record.exc_info
            redacted = self._redact(str(exc_value))
            if redacted != str(exc_value):
                try:
                    record.exc_info = (exc_type, exc_type(redacted), tb)
                except Exception:
                    # Exotic exception constructors may reject the call; fall
                    # back to a plain Exception so the traceback still logs,
                    # with the secret redacted.
                    record.exc_info = (Exception, Exception(redacted), tb)
        return True
