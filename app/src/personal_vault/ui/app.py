"""Main application window: picker, unlock, vault view, and the lock flow."""

from __future__ import annotations

import sys
from typing import cast

from PySide6.QtWidgets import QApplication, QMainWindow, QStackedWidget

from personal_vault.services import (
    Profile,
    VaultSession,
    clipboard_clear_seconds,
    idle_lock_minutes,
    lock_on_sleep,
    profiles,
)
from personal_vault.ui.clipboard import ClipboardGuard
from personal_vault.ui.idle import ActivityFilter, IdleMonitor
from personal_vault.ui.picker import ProfilePicker
from personal_vault.ui.unlock import UnlockWindow
from personal_vault.ui.vault_view import VaultView


class App(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Personal Vault")
        self._session: VaultSession | None = None
        self._unlock: UnlockWindow | None = None
        self._guard: ClipboardGuard | None = None
        self._monitor: IdleMonitor | None = None
        self._filter: ActivityFilter | None = None
        self._stack = QStackedWidget(self)
        self._picker = ProfilePicker(self)
        self._stack.addWidget(self._picker)
        self.setCentralWidget(self._stack)
        self._picker.opened.connect(self._on_opened)

    def _on_opened(self, profile_id: str) -> None:
        profile = self._profile_by_id(profile_id)
        if profile is None:
            return
        self._unlock = UnlockWindow(profile, self)
        self._unlock.unlocked.connect(self._on_unlocked)
        self._stack.addWidget(self._unlock)
        self._stack.setCurrentWidget(self._unlock)

    def _on_unlocked(self, session: VaultSession) -> None:
        self._session = session
        self._guard = ClipboardGuard(clipboard_clear_seconds(), self)
        self._monitor = IdleMonitor(idle_lock_minutes(), lock_on_sleep(), self)
        self._monitor.locked.connect(self._lock)
        self._filter = ActivityFilter(self._monitor, self)
        app = cast(QApplication, QApplication.instance())
        app.installEventFilter(self._filter)
        view = VaultView(session)
        view.locked.connect(self._lock)
        view.restored.connect(self._on_restored)
        self._stack.addWidget(view)
        self._stack.setCurrentIndex(self._stack.count() - 1)

    def _on_restored(self, session: VaultSession) -> None:
        """A backup restore replaced the vault file; rebuild the unlocked state."""
        self._lock()
        self._on_unlocked(session)

    def _lock(self) -> None:
        """Drop the session, clear the clipboard, return to the unlock screen."""
        if self._guard is not None:
            self._guard.clear()
        if self._monitor is not None:
            self._monitor.stop()
        if self._filter is not None:
            app = cast(QApplication, QApplication.instance())
            app.removeEventFilter(self._filter)
        self._session = None
        widget = self._stack.currentWidget()
        if self._unlock is not None and widget is not None and widget is not self._unlock:
            self._stack.removeWidget(widget)
            widget.deleteLater()
            self._stack.setCurrentWidget(self._unlock)

    def _profile_by_id(self, profile_id: str) -> Profile | None:
        return next((p for p in profiles().list() if p.id == profile_id), None)


def run() -> int:
    app = QApplication(sys.argv)
    window = App()
    window.show()
    return app.exec()
