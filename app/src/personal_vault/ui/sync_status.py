"""M5-06: the sync status line, and the buttons that turn Drive sync on and off.

The line says exactly one of the states sync.md lists — Synced, Waiting to
upload, Offline, Conflict, Reconnect Google, Sync off — and nothing here
changes a file: linking stores a token in the vault, unlinking removes it,
"Sync now" asks the worker to run, and every conflict ends through the
banner's own three choices.

Linking opens a browser and blocks, so it runs on a thread of its own and
comes back through signals; everything else is quick enough for the GUI
thread.
"""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
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
    Status,
    SyncController,
    SyncReport,
    SyncResult,
    VaultSession,
    clipboard_clear_seconds,
    get_login,
    google_client_secret_path,
    install_client_secret,
    list_logins,
    review_copy,
)
from personal_vault.ui.clipboard import ClipboardGuard
from personal_vault.ui.sync_banner import ConflictActions, SyncOutcome

log = logging.getLogger("personal_vault.ui")

TITLES: dict[Status, str] = {
    Status.SYNCED: "Synced",
    Status.WAITING: "Waiting to upload",
    Status.OFFLINE: "Offline",
    Status.CONFLICT: "Conflict",
    Status.RECONNECT: "Reconnect Google",
    Status.UNREADABLE: "Needs attention",
    Status.ATTENTION: "Needs attention",
    Status.SYNC_OFF: "Sync off",
}


def outcome_of(result: SyncResult) -> SyncOutcome:
    """A sync result as the banner needs it: did it work, and what to say."""
    return SyncOutcome(
        ok=result.status in {Status.SYNCED, Status.WAITING},
        message=result.message,
        adopted=result.adopted,
    )


def _retry_time(value: str | None) -> str:
    """The retry time in the reader's clock, or nothing if it is unreadable."""
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%H:%M")
    except ValueError:
        return ""


class ConflictCopyDialog(QDialog):
    """The kept copy of Drive's vault, read-only, to copy entries from by hand.

    This is "Open both": a window beside the vault for looking at the other
    version. Its passwords copy through the same guarded clipboard as the
    vault's own, and the copy is closed when the window is.
    """

    def __init__(
        self,
        session: VaultSession,
        path: str | Path,
        *,
        clear_seconds: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._guard = ClipboardGuard(clear_seconds, self)
        self._entry: LoginEntry | None = None
        self._copy = review_copy(session, path)
        self.setWindowTitle(f"Drive's copy — {Path(path).name} (read-only)")

        self._list = QListWidget()
        for summary in list_logins(self._copy):
            item = QListWidgetItem(f"{summary.title} — {summary.username}")
            item.setData(Qt.ItemDataRole.UserRole, str(summary.id))
            self._list.addItem(item)
        self._list.currentItemChanged.connect(lambda *_: self._show_selected())

        self._title = QLineEdit()
        self._username = QLineEdit()
        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        for field in (self._title, self._username, self._password):
            field.setReadOnly(True)

        self._show_password = QCheckBox("Show password")
        self._show_password.toggled.connect(
            lambda visible: self._password.setEchoMode(
                QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
            )
        )
        self.copy_button = QPushButton("Copy password")
        self.copy_button.clicked.connect(self._copy_password)
        self.copy_button.setEnabled(False)

        form = QVBoxLayout()
        for label, field in (("Title", self._title), ("Username", self._username)):
            form.addWidget(QLabel(label))
            form.addWidget(field)
        form.addWidget(QLabel("Password"))
        password_row = QHBoxLayout()
        password_row.addWidget(self._password)
        password_row.addWidget(self._show_password)
        form.addLayout(password_row)
        form.addWidget(self.copy_button)

        layout = QHBoxLayout(self)
        layout.addWidget(self._list, 1)
        layout.addLayout(form, 1)

    def _show_selected(self) -> None:
        item = self._list.currentItem()
        if item is None:
            return
        entry_id = uuid.UUID(str(item.data(Qt.ItemDataRole.UserRole)))
        self._entry = get_login(self._copy, entry_id)
        self._title.setText(self._entry.title)
        self._username.setText(self._entry.username)
        self._password.setText(self._entry.password.reveal())
        self.copy_button.setEnabled(True)

    def _copy_password(self) -> None:
        if self._entry is not None:
            self._guard.copy(self._entry.password.reveal())

    def closeEvent(self, event: object) -> None:
        self._guard.clear()  # nothing of theirs stays on the clipboard
        self._copy.close()
        super().closeEvent(event)  # type: ignore[arg-type]


class SyncStatusBar(QWidget):
    """The status line, its two buttons, and the link to the conflict banner."""

    conflict_ready = Signal(object, object)  # (conflict dict or None, ConflictActions)
    sync_applied = Signal(object)  # a SyncOutcome that replaced the vault file
    _linked = Signal(str)
    _link_failed = Signal(str)

    def __init__(self, controller: SyncController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._controller = controller
        self._conflict_key: object = None

        self._title_label = QLabel()
        self._title_label.setStyleSheet("font-weight: bold")
        self._detail_label = QLabel()
        self._detail_label.setWordWrap(True)

        self.link_button = QPushButton("Link Google Drive")
        self.unlink_button = QPushButton("Unlink")
        self.sync_button = QPushButton("Sync now")
        # the first link's question (ADR-010): two copies, one has to win
        self.drive_button = QPushButton("Use Drive's copy")
        self.vault_button = QPushButton("Keep this vault")
        self.link_button.clicked.connect(self._link_flow)
        self.unlink_button.clicked.connect(self._unlink_flow)
        self.sync_button.clicked.connect(self._sync_now)
        self.drive_button.clicked.connect(lambda: self._choose_first_copy("drive"))
        self.vault_button.clicked.connect(lambda: self._choose_first_copy("vault"))
        self._linked.connect(self._on_linked)
        self._link_failed.connect(self._on_link_failed)

        row = QHBoxLayout(self)
        row.addWidget(self._title_label)
        row.addWidget(self._detail_label, 1)
        row.addWidget(self.link_button)
        row.addWidget(self.drive_button)
        row.addWidget(self.vault_button)
        row.addWidget(self.unlink_button)
        row.addWidget(self.sync_button)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self.refresh()

    # --- what the line is saying (the tests read these) ---------------------

    @property
    def controller(self) -> SyncController:
        return self._controller

    @property
    def title(self) -> str:
        return self._title_label.text()

    @property
    def detail(self) -> str:
        return self._detail_label.text()

    def stop(self) -> None:
        """Stop polling (the view is going away)."""
        self._timer.stop()

    def refresh(self) -> None:
        """Read the controller and say what it says."""
        report = self._controller.report()
        self._title_label.setText(TITLES.get(report.status, report.message))
        self._detail_label.setText(self._detail_for(report))
        linked = self._controller.linked()
        self.link_button.setVisible(not linked)
        self.unlink_button.setVisible(linked)
        self.sync_button.setVisible(linked)
        self.sync_button.setEnabled(linked and self._controller.running)
        self.drive_button.setVisible(report.first_link)
        self.vault_button.setVisible(report.first_link)
        self._offer_conflict(report)

    def _detail_for(self, report: SyncReport) -> str:
        if report.status is Status.CONFLICT:
            said = "action needed"
        elif report.status is Status.OFFLINE:
            when = _retry_time(report.retry_at)
            said = f"retrying at {when}" if when else "retrying"
        else:
            said = report.message
        return " · ".join(part for part in (said, report.email) if part)

    # --- conflicts ----------------------------------------------------------

    def _offer_conflict(self, report: SyncReport) -> None:
        """Tell the view about a conflict once, not on every tick."""
        conflict = report.conflict
        key = None if conflict is None else (conflict.get("detected_at"), conflict.get("kept_path"))
        if key == self._conflict_key:
            return
        self._conflict_key = key
        self.conflict_ready.emit(None if conflict is None else dict(conflict), self._actions())

    def _actions(self) -> ConflictActions:
        return ConflictActions(
            keep_mine=lambda: outcome_of(self._controller.keep_mine()),
            take_theirs=lambda: outcome_of(self._controller.take_theirs()),
            open_theirs=self._open_theirs,
            merge_both=lambda: outcome_of(self._controller.merge_both()),
        )

    def _open_theirs(self, path: Path) -> None:
        ConflictCopyDialog(
            self._controller.session(),
            path,
            clear_seconds=clipboard_clear_seconds(),
            parent=self,
        ).exec()

    # --- the first link, when Drive already has a copy ----------------------

    def _choose_first_copy(self, which: str) -> None:
        """Answer the first link's question with one of the engine's own methods."""
        action = self._controller.take_theirs if which == "drive" else self._controller.keep_mine
        self._set_first_link_enabled(False)
        try:
            outcome = outcome_of(action())
        except Exception as exc:  # noqa: BLE001 — a click must report, never crash
            self.refresh()
            self._set_first_link_enabled(True)
            self._detail_label.setText(f"That did not work: {exc}")
            return
        self.refresh()
        if not outcome.ok:
            self._set_first_link_enabled(True)  # the other choice is still there
            self._detail_label.setText(outcome.message)
            return
        self._controller.start()  # there is a state now: sync runs from here
        self._controller.sync_now()  # and one run so the line stops showing the ask
        self.sync_applied.emit(outcome)  # the view reloads if our file was replaced

    def _set_first_link_enabled(self, enabled: bool) -> None:
        for button in (self.drive_button, self.vault_button):
            button.setEnabled(enabled)

    # --- linking, unlinking, syncing now ------------------------------------

    def _link_flow(self) -> None:
        if not google_client_secret_path().exists():
            chosen, _ = QFileDialog.getOpenFileName(
                self, "Choose your Google client file", "", "JSON files (*.json)"
            )
            if not chosen:
                return
            try:
                install_client_secret(chosen)
            except Exception as exc:  # noqa: BLE001 — the file may be the wrong one
                self._detail_label.setText(f"That file could not be used: {exc}")
                return
        self._detail_label.setText("Waiting for you to finish signing in with Google…")
        self.link_button.setEnabled(False)
        threading.Thread(target=self._run_link, name="vault-link", daemon=True).start()

    def _run_link(self) -> None:
        try:
            account = self._controller.link()
        except Exception as exc:  # noqa: BLE001 — report it, never crash the thread
            log.debug("link failed: %s", type(exc).__name__)
            self._link_failed.emit(str(exc))
            return
        self._linked.emit(account.email or "your Google account")

    def _on_linked(self, who: str) -> None:
        self._controller.start()
        self.link_button.setEnabled(True)
        self.refresh()
        log.debug("linked to Drive as %s", who)

    def _on_link_failed(self, message: str) -> None:
        self._detail_label.setText(f"Could not connect to Google Drive: {message}")
        self.link_button.setEnabled(True)

    def _unlink_flow(self) -> None:
        answer = QMessageBox.question(
            self,
            "Unlink Google Drive",
            "Stop syncing this profile and forget the sign-in? "
            "The vault on this computer stays exactly as it is.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._controller.unlink()
        self.refresh()

    def _sync_now(self) -> None:
        self._controller.sync_now()
        self.refresh()
