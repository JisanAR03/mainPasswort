"""M2-04: the generator dialog and its hook in the entry form (pytest-qt)."""

from __future__ import annotations

import logging

import pytest
from personal_vault.services import SecretStr
from personal_vault.ui import entry_form
from personal_vault.ui.entry_form import EntryFormDialog
from personal_vault.ui.generator_dialog import GeneratorDialog
from PySide6.QtWidgets import QDialog, QLineEdit
from pytestqt.qtbot import QtBot


@pytest.fixture
def dialog(qtbot: QtBot) -> GeneratorDialog:
    widget = GeneratorDialog()
    qtbot.addWidget(widget)
    return widget


def _digits_only(dialog: GeneratorDialog, length: int = 12) -> str:
    for box in (dialog._upper, dialog._lower, dialog._symbols):
        box.setChecked(False)
    dialog._digits.setChecked(True)
    dialog._length.setValue(length)
    return dialog._preview.text()


def test_preview_matches_current_options(dialog: GeneratorDialog) -> None:
    preview = _digits_only(dialog, 12)
    assert len(preview) == 12
    # look-alikes are excluded by default, so 0 and 1 never appear
    assert set(preview) <= set("23456789")


def test_regenerate_changes_the_value(dialog: GeneratorDialog) -> None:
    previews = {dialog._preview.text()}
    for _ in range(4):
        dialog._regenerate.click()
        previews.add(dialog._preview.text())
    assert len(previews) > 1


def test_disabling_a_class_removes_its_characters(dialog: GeneratorDialog) -> None:
    for box in (dialog._upper, dialog._digits, dialog._symbols):
        box.setChecked(False)
    dialog._lower.setChecked(True)
    preview = dialog._preview.text()
    assert preview
    assert set(preview) <= set("abcdefghijkmnpqrstuvwxyz")  # minus look-alikes o, l


def test_invalid_options_disable_buttons_and_show_why(dialog: GeneratorDialog) -> None:
    for box in (dialog._upper, dialog._lower, dialog._digits, dialog._symbols):
        box.setChecked(False)
    assert not dialog._regenerate.isEnabled()
    assert not dialog._use.isEnabled()
    assert not dialog._error.isHidden()
    assert "character class" in dialog._error.text()
    assert dialog._preview.text() == ""
    dialog._upper.setChecked(True)
    assert dialog._regenerate.isEnabled()
    assert dialog._use.isEnabled()
    assert dialog._preview.text()


def test_length_out_of_bounds_is_impossible(dialog: GeneratorDialog) -> None:
    assert dialog._length.minimum() == 4
    assert dialog._length.maximum() == 4096


def test_preview_is_masked_by_default(dialog: GeneratorDialog) -> None:
    assert dialog._preview.echoMode() == QLineEdit.EchoMode.Password
    dialog._show.setChecked(True)
    assert dialog._preview.echoMode() == QLineEdit.EchoMode.Normal
    dialog._show.setChecked(False)
    assert dialog._preview.echoMode() == QLineEdit.EchoMode.Password


def test_preview_never_logs(dialog: GeneratorDialog, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG, logger="personal_vault.ui"):
        preview = _digits_only(dialog)
        dialog._regenerate.click()
        dialog.accept()
    assert preview not in caplog.text


def test_accept_sets_selected(dialog: GeneratorDialog) -> None:
    dialog._use.click()
    assert dialog.selected is not None
    assert dialog.selected.reveal() == dialog._preview.text()


def test_use_this_password_fills_the_entry_form(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    canary = "CANARY-generated-password"

    class FakeGenerator:
        DialogCode = QDialog.DialogCode
        selected = SecretStr(canary)

        def __init__(self, parent=None):  # noqa: ARG002
            pass

        def exec(self):
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(entry_form, "GeneratorDialog", FakeGenerator)
    form = EntryFormDialog()
    qtbot.addWidget(form)
    form._generate_button.click()
    assert form._password.text() == canary
