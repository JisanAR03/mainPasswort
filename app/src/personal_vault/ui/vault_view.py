"""Vault view (M2-03): searchable entry list, add/edit/delete, history.

Deletes move entries to the Recycle Bin and always ask first. Save goes
through services (atomic write, verify, backups) after every change.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from datetime import UTC

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from personal_vault.services import (
    LoginEntry,
    SyncController,
    VaultError,
    VaultSession,
    add_login,
    delete_login,
    entry_history,
    get_login,
    list_logins,
    save_vault,
    search_logins,
    update_login,
    vault_profile_id,
)
from personal_vault.ui.backups_view import BackupsView
from personal_vault.ui.entry_form import EntryFormDialog
from personal_vault.ui.sync_banner import ConflictActions, SyncBanner, SyncOutcome
from personal_vault.ui.sync_status import SyncStatusBar
from personal_vault.ui.transfer_dialogs import ExportDialog, ImportDialog

log = logging.getLogger("personal_vault.ui")


class HistoryDialog(QDialog):
    """Read-only list of an entry's previous versions, newest first."""

    def __init__(self, title: str, entries: list[LoginEntry]) -> None:
        super().__init__()
        self.setWindowTitle(f"History — {title}")
        self._list = QListWidget()
        for entry in reversed(entries):
            when = entry.updated_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
            self._list.addItem(f"{when} — {entry.title}")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Previous versions (read-only):"))
        layout.addWidget(self._list)


class VaultView(QWidget):
    """The unlocked vault: list, search, add, edit, delete, history."""

    locked = Signal()
    restored = Signal(object)  # a backup restore produced a new VaultSession
    sync_resolved = Signal(object)  # a conflict was resolved: the sync layer's outcome

    def __init__(self, session: VaultSession) -> None:
        super().__init__()
        self._session = session
        self._controller: SyncController | None = None
        self.sync: SyncStatusBar | None = None
        if vault_profile_id(session) is not None:  # a real profile vault may sync
            self._controller = SyncController(session)
            self.sync = SyncStatusBar(self._controller)
            self.sync.conflict_ready.connect(self.set_conflict)
            self.sync.sync_applied.connect(self._sync_resolved)
            controller = self._controller
            self.destroyed.connect(lambda *_: controller.stop())  # locking stops syncing
            self._controller.start()  # the unlock trigger, if this profile is linked

        self.banner = SyncBanner()
        self.banner.resolved.connect(self._sync_resolved)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search title, username or notes")
        self._search.textChanged.connect(self._refresh)

        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(self._edit_selected)

        self._add_button = QPushButton("Add")
        self._edit_button = QPushButton("Edit")
        self._history_button = QPushButton("History")
        self._delete_button = QPushButton("Delete")
        self._lock_button = QPushButton("Lock")
        self._export_button = QPushButton("Export…")
        self._import_button = QPushButton("Import…")
        self._backups_button = QPushButton("Backups")
        self._add_button.clicked.connect(self._add_flow)
        self._edit_button.clicked.connect(self._edit_selected)
        self._history_button.clicked.connect(self._show_history)
        self._delete_button.clicked.connect(self._delete_flow)
        self._lock_button.clicked.connect(self.locked)
        self._export_button.clicked.connect(self._export_flow)
        self._import_button.clicked.connect(self._import_flow)
        self._backups_button.clicked.connect(self._backups_flow)
        self._list.currentItemChanged.connect(lambda *_: self._update_buttons())

        buttons = QHBoxLayout()
        for button in (
            self._add_button,
            self._edit_button,
            self._history_button,
            self._delete_button,
            self._export_button,
            self._import_button,
            self._backups_button,
            self._lock_button,
        ):
            buttons.addWidget(button)

        layout = QVBoxLayout(self)
        if self.sync is not None:
            layout.addWidget(self.sync)
        layout.addWidget(self.banner)
        layout.addWidget(self._search)
        layout.addWidget(self._list)
        layout.addLayout(buttons)
        self._refresh()

    def set_conflict(self, conflict: Mapping[str, object] | None, actions: ConflictActions) -> None:
        """Show or clear the conflict banner (the sync layer calls this)."""
        if conflict is None:
            self.banner.clear()
        else:
            self.banner.show_conflict(conflict, actions)

    def _sync_resolved(self, outcome: object) -> None:
        """A conflict is over: reload the list, and the vault if Drive's copy won."""
        if self.sync is not None:
            self.sync.refresh()
        adopted = isinstance(outcome, SyncOutcome) and outcome.adopted
        if adopted and self._controller is not None:
            try:
                self._session = self._controller.reload()
            except VaultError as exc:
                self._warn(f"The copy from Drive could not be opened: {exc}")
                return
            self._refresh()
            self.restored.emit(self._session)  # the window reopens the vault
        else:
            self._refresh()
        self.sync_resolved.emit(outcome)

    def _refresh(self) -> None:
        query = self._search.text().strip()
        entries = search_logins(self._session, query) if query else list_logins(self._session)
        self._list.clear()
        for summary in entries:
            item = QListWidgetItem(f"{summary.title} — {summary.username}")
            item.setData(Qt.ItemDataRole.UserRole, str(summary.id))
            self._list.addItem(item)
        self._update_buttons()

    def _update_buttons(self) -> None:
        has_selection = self._list.currentItem() is not None
        self._edit_button.setEnabled(has_selection)
        self._history_button.setEnabled(has_selection)
        self._delete_button.setEnabled(has_selection)

    def _selected_id(self) -> uuid.UUID | None:
        item = self._list.currentItem()
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return uuid.UUID(str(value)) if value is not None else None

    def _warn(self, message: str) -> None:
        QMessageBox.warning(self, "Personal Vault", message)

    def _save(self) -> bool:
        try:
            save_vault(self._session)
        except VaultError as exc:
            self._warn(f"The vault could not be saved: {exc}")
            return False
        if self._controller is not None:
            self._controller.notify_saved()  # sync.md: upload a moment after a save
        return True

    def _add_flow(self) -> None:
        dialog = EntryFormDialog()
        while dialog.exec() == QDialog.DialogCode.Accepted:
            entry = dialog.result_entry
            if entry is None:
                return
            try:
                add_login(self._session, entry)
            except ValueError as exc:
                self._warn(str(exc))
                continue  # dialog re-opens with the fields intact
            if not self._save():
                return
            log.debug("saved entry %s", entry.id)  # the id, never a field (rule 3)
            self._refresh()
            return

    def _edit_selected(self) -> None:
        entry_id = self._selected_id()
        if entry_id is None:
            return
        dialog = EntryFormDialog(get_login(self._session, entry_id))
        while dialog.exec() == QDialog.DialogCode.Accepted:
            entry = dialog.result_entry
            if entry is None:
                return
            try:
                update_login(self._session, entry)
            except ValueError as exc:
                self._warn(str(exc))
                continue
            if not self._save():
                return
            log.debug("saved entry %s", entry.id)  # the id, never a field (rule 3)
            self._refresh()
            return

    def _show_history(self) -> None:
        entry_id = self._selected_id()
        if entry_id is None:
            return
        entry = get_login(self._session, entry_id)
        dialog = HistoryDialog(entry.title, entry_history(self._session, entry_id))
        dialog.exec()

    def _delete_flow(self) -> None:
        entry_id = self._selected_id()
        if entry_id is None:
            return
        entry = get_login(self._session, entry_id)
        answer = QMessageBox.question(
            self,
            "Delete entry",
            f'Delete "{entry.title}"? It moves to the Recycle Bin.',
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            delete_login(self._session, entry_id)
        except ValueError as exc:
            self._warn(str(exc))
            return
        if not self._save():
            return
        self._refresh()

    def _export_flow(self) -> None:
        ExportDialog(self._session, self).exec()

    def _import_flow(self) -> None:
        dialog = ImportDialog(self._session, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if not self._save():
                return
            QMessageBox.information(
                self,
                "Personal Vault",
                f"Imported {dialog.imported_count} entries into a new group for review.",
            )

    def _backups_flow(self) -> None:
        dialog = BackupsView(self._session, self)
        dialog.restored.connect(self.restored)
        dialog.exec()
