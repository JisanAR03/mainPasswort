"""Entry form dialog (M2-03): add and edit one login entry.

The dialog only collects fields; core validation runs when the caller saves
through services, and an invalid entry keeps the dialog open with the fields
intact. Passwords are masked by default.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
)

from personal_vault.services import LoginEntry, SecretStr
from personal_vault.ui.generator_dialog import GeneratorDialog


class EntryFormDialog(QDialog):
    """Collects the fields of a LoginEntry; result_entry is set on accept."""

    def __init__(self, entry: LoginEntry | None = None) -> None:
        super().__init__()
        self.setWindowTitle("Edit entry" if entry else "New entry")
        self._entry = entry
        self.result_entry: LoginEntry | None = None

        self._title = QLineEdit()
        self._username = QLineEdit()
        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        self._show_password = QCheckBox("Show password")
        self._show_password.toggled.connect(self._toggle_password)
        self._urls = QPlainTextEdit()
        self._urls.setPlaceholderText("One URL per line, http or https")
        self._notes = QPlainTextEdit()
        self._tags = QLineEdit()
        self._tags.setPlaceholderText("Comma-separated")
        self._match_subdomains = QCheckBox("Also match subdomains")

        form = QFormLayout(self)
        form.addRow("Title", self._title)
        form.addRow("Username", self._username)
        password_row = QHBoxLayout()
        password_row.addWidget(self._password)
        password_row.addWidget(self._show_password)
        self._generate_button = QPushButton("Generate…")
        self._generate_button.clicked.connect(self._open_generator)
        password_row.addWidget(self._generate_button)
        form.addRow("Password", password_row)
        form.addRow("URLs", self._urls)
        form.addRow("Notes", self._notes)
        form.addRow("Tags", self._tags)
        form.addRow("", self._match_subdomains)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        form.addRow(self._buttons)

        if entry is not None:
            self._fill(entry)

    def _fill(self, entry: LoginEntry) -> None:
        self._title.setText(entry.title)
        self._username.setText(entry.username)
        self._password.setText(entry.password.reveal())
        self._urls.setPlainText("\n".join(entry.urls))
        self._notes.setPlainText(entry.notes)
        self._tags.setText(", ".join(entry.tags))
        self._match_subdomains.setChecked(entry.match_subdomains)

    def _toggle_password(self, visible: bool) -> None:
        self._password.setEchoMode(
            QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        )

    def _open_generator(self) -> None:
        dialog = GeneratorDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selected is not None:
            self._password.setText(dialog.selected.reveal())

    def accept(self) -> None:
        now = datetime.now(UTC)
        existing = self._entry
        self.result_entry = LoginEntry(
            id=existing.id if existing else uuid.uuid4(),
            title=self._title.text(),
            username=self._username.text(),
            password=SecretStr(self._password.text()),
            urls=[line.strip() for line in self._urls.toPlainText().splitlines() if line.strip()],
            notes=self._notes.toPlainText(),
            tags=[tag.strip() for tag in self._tags.text().split(",") if tag.strip()],
            match_subdomains=self._match_subdomains.isChecked(),
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        super().accept()
