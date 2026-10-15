"""Pairing confirmation dialog: the code the browser shows must match ours."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)


class PairingDialog(QDialog):
    """ "Pair this browser?" with the 6-character code and Pair / Cancel."""

    def __init__(self, browser_name: str, code: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Pair browser")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("A browser extension wants to pair with this vault."))
        layout.addWidget(QLabel(f"Browser: {browser_name}"))
        layout.addWidget(QLabel(f"Pair only if the browser shows the same code:\n\n{code}"))
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        pair = buttons.button(QDialogButtonBox.StandardButton.Ok)
        pair.setText("Pair")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


def confirm_pairing(browser_name: str, code: str) -> bool:
    """Show the dialog; True only when the user clicks Pair."""
    dialog = PairingDialog(browser_name, code)
    return dialog.exec() == QDialog.DialogCode.Accepted
