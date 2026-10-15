"""Clipboard copy with auto-clear ([S], M2-05).

A ClipboardGuard copies a value to the clipboard and starts a single-shot
timer that clears it after the configured number of seconds. Every copy
restarts the timer, explicit clear stops it, and empty values are ignored.

Qt offers no cross-platform way to mark clipboard content so that clipboard
history and cloud-sync features skip it (Windows CF_EXCLUDE and the macOS
transient type need native code), so that is not attempted here. The value
simply never stays on the clipboard longer than the configured delay.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication

log = logging.getLogger("personal_vault.ui")


class ClipboardGuard(QObject):
    """Copies non-empty values to the clipboard and clears them on a timer."""

    def __init__(self, clear_seconds: int, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._seconds = max(1, clear_seconds)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(self._seconds * 1000)
        self._timer.timeout.connect(self.clear)

    def copy(self, value: str) -> None:
        """Copy a value and (re)start the clear timer; an empty value is a no-op."""
        if not value:
            return
        QApplication.clipboard().setText(value)
        self._timer.start()
        log.debug("clipboard set; clearing in %ss", self._seconds)

    def clear(self) -> None:
        """Clear the clipboard and stop the timer (also called on timeout)."""
        self._timer.stop()
        QApplication.clipboard().clear()
        log.debug("clipboard cleared")

    def active(self) -> bool:
        """Whether the auto-clear timer is currently running."""
        return self._timer.isActive()
