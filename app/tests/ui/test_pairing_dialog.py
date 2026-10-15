"""M3-03: the pairing dialog shows the code and Pair/Cancel decide the result."""

from __future__ import annotations

import pytest
from personal_vault.ui.pairing_dialog import PairingDialog, confirm_pairing
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel
from pytestqt.qtbot import QtBot

pytestmark = pytest.mark.ui

BROWSER = "Chrome"
CODE = "AB2CD4"


def test_dialog_shows_browser_name_and_code(qtbot: QtBot) -> None:
    dialog = PairingDialog(BROWSER, CODE)
    qtbot.addWidget(dialog)
    labels = [label.text() for label in dialog.findChildren(QLabel)]
    assert any(BROWSER in text for text in labels)
    assert any(CODE in text for text in labels)


def test_pair_button_accepts(qtbot: QtBot) -> None:
    dialog = PairingDialog(BROWSER, CODE)
    qtbot.addWidget(dialog)
    dialog.show()
    pair = dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok)
    assert pair is not None and pair.text() == "Pair"
    qtbot.mouseClick(pair, Qt.MouseButton.LeftButton)
    assert dialog.result() == int(QDialog.DialogCode.Accepted)


def test_cancel_button_rejects(qtbot: QtBot) -> None:
    dialog = PairingDialog(BROWSER, CODE)
    qtbot.addWidget(dialog)
    dialog.show()
    cancel = dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Cancel)
    assert cancel is not None
    qtbot.mouseClick(cancel, Qt.MouseButton.LeftButton)
    assert dialog.result() == int(QDialog.DialogCode.Rejected)


def test_confirm_pairing_returns_the_dialog_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(PairingDialog, "exec", staticmethod(lambda *a: QDialog.DialogCode.Accepted))
    assert confirm_pairing(BROWSER, CODE) is True
    monkeypatch.setattr(PairingDialog, "exec", staticmethod(lambda *a: QDialog.DialogCode.Rejected))
    assert confirm_pairing(BROWSER, CODE) is False
