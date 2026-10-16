"""Unlock window (M2-02): master password entry for one profile."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QShowEvent
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
    profile_vault_path,
)

MIN_PASSWORD_LENGTH = 12


class UnlockWindow(QWidget):
    """Asks for the master password; the unlock button needs ≥ 12 characters.

    A profile whose vault file does not exist yet has never been opened: the
    window asks for a *new* master password instead, and the unlock creates
    the vault (the service does that; this window only says so).
    """

    unlocked = Signal(object)  # VaultSession

    def __init__(self, profile: Profile, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._profile = profile
        self._creating = False
        self._title = QLabel()
        self._title.setObjectName("unlockTitle")
        self._hint = QLabel()
        self._hint.setWordWrap(True)
        self._password = QLineEdit()
        self._password.setObjectName("passwordField")
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        self._password.setPlaceholderText(
            f"Master password (at least {MIN_PASSWORD_LENGTH} characters)"
        )
        self._unlock_button = QPushButton()
        self._unlock_button.setEnabled(False)
        self._unlock_button.clicked.connect(self._try_unlock)
        self._password.textChanged.connect(self._update_button)
        self._password.returnPressed.connect(self._try_unlock)
        self._set_mode()

        layout = QVBoxLayout(self)
        layout.addWidget(self._title)
        layout.addWidget(self._hint)
        layout.addWidget(self._password)
        layout.addWidget(self._unlock_button)

    def _set_mode(self) -> None:
        """Ask to create the vault when there is none, and to unlock it when there is.

        Re-run on every show: the app keeps this window for the life of the
        profile, and the one that just created a vault must stop offering to
        create it (the lock path returns to this same window).
        """
        self._creating = not profile_vault_path(self._profile).exists()
        name = self._profile.display_name
        if self._creating:
            self._title.setText(f"Create {name}")
            self._hint.setText(
                "This profile has no vault yet. The password you choose now becomes its "
                "master password, so make it a passphrase: several random words are easier "
                "to remember and harder to guess."
            )
        else:
            self._title.setText(f"Unlock {name}")
            self._hint.setText(
                "Use a passphrase: several random words are easier to remember and harder to guess."
            )
        self._unlock_button.setText("Create vault" if self._creating else "Unlock")

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 (Qt naming)
        super().showEvent(event)
        self._set_mode()

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
