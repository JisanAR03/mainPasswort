"""M2-03: the entry form dialog (pytest-qt)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fixtures.weak_vault import WEAK_PASSWORD, build_weak_vault
from personal_vault.core.vault import VaultSession
from personal_vault.services import add_login
from personal_vault.ui.entry_form import EntryFormDialog
from PySide6.QtWidgets import QLineEdit
from pytestqt.qtbot import QtBot


@pytest.fixture
def session(tmp_path: Path) -> VaultSession:
    path = build_weak_vault(tmp_path / "vault.kdbx")
    return VaultSession.open(path, WEAK_PASSWORD, tmp_path / "backups")


def test_password_masked_by_default(qtbot: QtBot) -> None:
    dialog = EntryFormDialog()
    qtbot.addWidget(dialog)
    assert dialog._password.echoMode() == QLineEdit.EchoMode.Password
    dialog._show_password.setChecked(True)
    assert dialog._password.echoMode() == QLineEdit.EchoMode.Normal
    dialog._show_password.setChecked(False)
    assert dialog._password.echoMode() == QLineEdit.EchoMode.Password


def test_every_field_round_trips_through_save_and_reload(session: VaultSession) -> None:
    dialog = EntryFormDialog()
    dialog._title.setText("Round Trip")
    dialog._username.setText("rt@example.com")
    dialog._password.setText("a round-trip password")
    dialog._urls.setPlainText("https://example.com/login\nhttps://example.org")
    dialog._notes.setPlainText("line one\nline two")
    dialog._tags.setText("work, school")
    dialog._match_subdomains.setChecked(True)
    dialog.accept()
    entry = dialog.result_entry
    assert entry is not None
    add_login(session, entry)
    session.save()

    stored = session.get(entry.id)
    assert stored.title == "Round Trip"
    assert stored.username == "rt@example.com"
    assert stored.password.reveal() == "a round-trip password"
    assert stored.urls == ["https://example.com/login", "https://example.org"]
    assert stored.notes == "line one\nline two"
    assert stored.tags == ["work", "school"]
    assert stored.match_subdomains is True


def test_validation_rejects_invalid_fields(session: VaultSession) -> None:
    for title, username, url in [
        ("", "user@example.com", "https://example.com"),  # empty title
        ("Site", "u" * 501, "https://example.com"),  # over-long username
        ("Site", "user@example.com", "ftp://example.com"),  # non-http URL
    ]:
        dialog = EntryFormDialog()
        dialog._title.setText(title)
        dialog._username.setText(username)
        dialog._urls.setPlainText(url)
        dialog.accept()
        assert dialog.result_entry is not None
        with pytest.raises(ValueError):
            add_login(session, dialog.result_entry)
