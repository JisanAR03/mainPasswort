"""Unlock window (M2-02): master password entry for one profile."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from personal_vault.services import (
    InvalidPassword,
    Profile,
    VaultCorrupted,
    open_profile_vault,
)

MIN_PASSWORD_LENGTH = 12


class UnlockWindow(QWidget):
    """Asks for the master password; the unlock button needs ≥ 12 characters."""

    unlocked = Signal(object)  # VaultSession

    def __init__(self, profile: Profile, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._profile = profile

        title = QLabel(f"Unlock {profile.display_name}")
        title.setObjectName("unlockTitle")
        hint = QLabel(
            "Use a passphrase: several random words are easier to remember and harder to guess."
        )
        hint.setWordWrap(True)
        self._password = QLineEdit()
        self._password.setObjectName("passwordField")
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        self._password.setPlaceholderText(
            f"Master password (at least {MIN_PASSWORD_LENGTH} characters)"
        )
        self._unlock_button = QPushButton("Unlock")
        self._unlock_button.setEnabled(False)
        self._unlock_button.clicked.connect(self._try_unlock)
        self._password.textChanged.connect(self._update_button)
        self._password.returnPressed.connect(self._try_unlock)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addWidget(self._password)
        layout.addWidget(self._unlock_button)

    def _update_button(self) -> None:
        self._unlock_button.setEnabled(len(self._password.text()) >= MIN_PASSWORD_LENGTH)

    def _try_unlock(self) -> None:
        password = self._password.text()
        if len(password) < MIN_PASSWORD_LENGTH:
            return
        try:
            session = open_profile_vault(self._profile, password)
        except InvalidPassword:
            self._fail("Wrong master password.")
        except VaultCorrupted:
            self._fail("The vault file is damaged and could not be read.")
        else:
            self._password.clear()
            self._update_button()
            self.unlocked.emit(session)

    def _fail(self, message: str) -> None:
        # The password never survives a failed attempt.
        self._password.clear()
        self._update_button()
        QMessageBox.warning(self, "Personal Vault", message)
