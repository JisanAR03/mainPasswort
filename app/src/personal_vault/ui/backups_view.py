"""Backups view (M2-08): list backups newest first, restore after confirmation.

Restoring replaces the vault file with the chosen backup and reopens it as a
new session; the dialog emits ``restored`` with that session and the caller
swaps it in. A backup that does not decrypt with the master password is
refused before anything is overwritten (VaultSession.restore_backup).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from personal_vault.services import (
    VaultError,
    VaultSession,
    list_backups,
    restore_backup,
)


class BackupsView(QDialog):
    """Lists backups and restores the chosen one after confirmation."""

    restored = Signal(object)  # the reopened VaultSession

    def __init__(self, session: VaultSession, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Backups")
        self._session = session
        self._backups: list[Path] = []

        self._list = QListWidget()
        self._restore_button = QPushButton("Restore selected backup")
        self._restore_button.clicked.connect(self._restore)
        self._close_button = QPushButton("Close")
        self._close_button.clicked.connect(self.accept)

        buttons = QHBoxLayout()
        buttons.addWidget(self._restore_button)
        buttons.addWidget(self._close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Restoring replaces the current vault with the chosen backup."))
        layout.addWidget(self._list)
        layout.addLayout(buttons)
        self._refresh()

    def _refresh(self) -> None:
        self._backups = list_backups(self._session)
        self._list.clear()
        for backup in self._backups:
            self._list.addItem(backup.name)
        self._restore_button.setEnabled(bool(self._backups))

    def _restore(self) -> None:
        row = self._list.currentRow()
        if row < 0:
            return
        backup = self._backups[row]
        answer = QMessageBox.question(
            self,
            "Restore backup",
            f"Restore {backup.name}? The current vault is replaced.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            session = restore_backup(self._session, backup)
        except VaultError as exc:
            self._warn(f"The backup could not be restored: {exc}")
            return
        self.restored.emit(session)
        self.accept()

    def _warn(self, message: str) -> None:
        QMessageBox.warning(self, "Personal Vault", message)
