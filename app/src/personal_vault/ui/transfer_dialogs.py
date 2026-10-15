"""Export and import dialogs (M2-08).

Export: encrypted KDBX is the default (optionally under a new password);
plaintext CSV needs the master password again AND a typed confirmation
(invariant I8) before services.export_csv may run.

Import: KDBX and CSV files are parsed as untrusted input with size limits
and land in a new group for review. Failures show a message, never a crash.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QWidget,
)

from personal_vault.services import (
    InvalidPassword,
    VaultError,
    VaultSession,
    export_csv,
    import_csv,
    import_kdbx,
    open_vault,
)

CSV_CONFIRMATION = "EXPORT"
NEW_PASSWORD_MIN_LENGTH = 12


class ExportDialog(QDialog):
    """KDBX export (default) or CSV export behind I8."""

    def __init__(self, session: VaultSession, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export")
        self._session = session

        self._kdbx_radio = QRadioButton("Encrypted KDBX copy")
        self._csv_radio = QRadioButton("Plaintext CSV (unencrypted)")
        self._kdbx_radio.setChecked(True)

        self._new_password = QLineEdit()
        self._new_password.setEchoMode(QLineEdit.EchoMode.Password)
        self._new_password.setPlaceholderText(
            f"New password (at least {NEW_PASSWORD_MIN_LENGTH} characters)"
        )

        self._master_password = QLineEdit()
        self._master_password.setEchoMode(QLineEdit.EchoMode.Password)
        self._master_password.setPlaceholderText("Master password again")

        self._confirmation = QLineEdit()
        self._confirmation.setPlaceholderText(f'Type "{CSV_CONFIRMATION}" to confirm')

        self._path = QLineEdit()
        self._choose_button = QPushButton("Choose file…")
        self._choose_button.clicked.connect(self._choose_path)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.accepted.connect(self._export)
        self._buttons.rejected.connect(self.reject)

        form = QFormLayout(self)
        form.addRow(self._kdbx_radio)
        form.addRow("New password", self._new_password)
        form.addRow(self._csv_radio)
        form.addRow("Master password", self._master_password)
        form.addRow("Confirmation", self._confirmation)
        form.addRow("File", self._path)
        form.addRow(self._choose_button)
        form.addRow(self._buttons)

        self._csv_radio.toggled.connect(self._update_state)
        self._update_state()

    def _update_state(self) -> None:
        csv_mode = self._csv_radio.isChecked()
        self._new_password.setEnabled(not csv_mode)
        self._master_password.setEnabled(csv_mode)
        self._confirmation.setEnabled(csv_mode)

    def _choose_path(self) -> None:
        if self._csv_radio.isChecked():
            chosen, _ = QFileDialog.getSaveFileName(self, "Export CSV", "", "CSV (*.csv)")
        else:
            chosen, _ = QFileDialog.getSaveFileName(self, "Export KDBX", "", "KDBX (*.kdbx)")
        if chosen:
            self._path.setText(chosen)

    def _export(self) -> None:
        target = self._path.text().strip()
        if not target:
            self._warn("Choose a file to export to.")
            return
        if self._kdbx_radio.isChecked():
            self._export_kdbx(target)
        else:
            self._export_csv(target)

    def _export_kdbx(self, target: str) -> None:
        password = self._new_password.text()
        if len(password) < NEW_PASSWORD_MIN_LENGTH:
            self._warn(f"The new password needs at least {NEW_PASSWORD_MIN_LENGTH} characters.")
            return
        try:
            self._session.export_kdbx(target, password)
        except (ValueError, VaultError) as exc:
            self._warn(f"The export failed: {exc}")
            return
        self.accept()

    def _export_csv(self, target: str) -> None:
        # Invariant I8: the master password must be entered again and a typed
        # confirmation must match before the plaintext export is written.
        try:
            open_vault(self._session.path, self._master_password.text())
        except InvalidPassword:
            self._warn("Wrong master password.")
            return
        except VaultError as exc:
            self._warn(f"The vault could not be checked: {exc}")
            return
        if self._confirmation.text() != CSV_CONFIRMATION:
            self._warn(f'Type "{CSV_CONFIRMATION}" to confirm the plaintext export.')
            return
        try:
            export_csv(self._session, target)
        except (ValueError, VaultError) as exc:
            self._warn(f"The export failed: {exc}")
            return
        self.accept()

    def _warn(self, message: str) -> None:
        QMessageBox.warning(self, "Personal Vault", message)


class ImportDialog(QDialog):
    """KDBX or CSV import, parsed as untrusted input into a new group."""

    def __init__(self, session: VaultSession, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Import")
        self._session = session
        self.imported_count = 0

        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        self._password.setPlaceholderText("Password of the KDBX file")

        self._path = QLineEdit()
        self._choose_button = QPushButton("Choose file…")
        self._choose_button.clicked.connect(self._choose_path)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.accepted.connect(self._import)
        self._buttons.rejected.connect(self.reject)

        form = QFormLayout(self)
        form.addRow("Password (KDBX only)", self._password)
        form.addRow("File", self._path)
        form.addRow(self._choose_button)
        form.addRow(self._buttons)

        self._path.textChanged.connect(self._update_state)
        self._update_state()

    def _update_state(self) -> None:
        suffix = Path(self._path.text().strip()).suffix.lower()
        self._password.setEnabled(suffix == ".kdbx")

    def _choose_path(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(self, "Import file", "", "Vaults (*.kdbx *.csv)")
        if chosen:
            self._path.setText(chosen)

    def _import(self) -> None:
        source = self._path.text().strip()
        if not source:
            self._warn("Choose a file to import.")
            return
        try:
            if Path(source).suffix.lower() == ".kdbx":
                self.imported_count = import_kdbx(source, self._password.text(), self._session)
            else:
                self.imported_count = import_csv(source, self._session)
        except (ValueError, InvalidPassword, VaultError) as exc:
            self._warn(f"The import failed: {exc}")
            return
        if self.imported_count == 0:
            self._warn("The file contains no entries to import.")
            return
        self.accept()

    def _warn(self, message: str) -> None:
        QMessageBox.warning(self, "Personal Vault", message)
