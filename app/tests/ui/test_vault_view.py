"""M2-03: the vault view: list, search, add, edit, history, delete (pytest-qt)."""

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path

import pytest
from fixtures.weak_vault import WEAK_PASSWORD, build_weak_vault, make_login
from personal_vault.core.vault import VaultSession
from personal_vault.services import SecretStr
from personal_vault.ui import vault_view
from personal_vault.ui.vault_view import VaultView
from PySide6.QtWidgets import QDialog, QMessageBox
from pytestqt.qtbot import QtBot


@pytest.fixture
def session(tmp_path: Path) -> VaultSession:
    path = build_weak_vault(tmp_path / "vault.kdbx")
    return VaultSession.open(path, WEAK_PASSWORD, tmp_path / "backups")


def _rows(view: VaultView) -> list[str]:
    return [view._list.item(i).text() for i in range(view._list.count())]


def _select_row(view: VaultView, row: int) -> None:
    view._list.setCurrentRow(row)


def _fake_form(entry=None):
    """A stand-in form that accepts immediately with a fixed result entry."""
    replacement = entry if entry is not None else make_login(title="Fresh Entry")

    class FakeForm:
        DialogCode = QDialog.DialogCode

        def __init__(self, existing=None):
            if existing is None:
                self.result_entry = replacement
            else:
                self.result_entry = replace(
                    replacement, id=existing.id, created_at=existing.created_at
                )

        def exec(self):
            return QDialog.DialogCode.Accepted

    return FakeForm


def test_list_shows_titles_and_usernames_never_passwords(
    qtbot: QtBot, session: VaultSession
) -> None:
    session.add(make_login(title="GitHub", username="gh@example.com"))
    session.add(make_login(title="Mail", username="mail@example.com"))
    view = VaultView(session)
    qtbot.addWidget(view)
    rows = _rows(view)
    assert "GitHub — gh@example.com" in rows
    assert "Mail — mail@example.com" in rows
    assert "correct horse battery staple" not in " ".join(rows)


def test_search_filters_by_title_username_notes(qtbot: QtBot, session: VaultSession) -> None:
    session.add(make_login(title="GitHub", username="gh@example.com", notes="work"))
    session.add(make_login(title="Mail", username="mail@example.com", notes="personal"))
    view = VaultView(session)
    qtbot.addWidget(view)
    view._search.setText("github")
    assert _rows(view) == ["GitHub — gh@example.com"]
    view._search.setText("personal")
    assert _rows(view) == ["Mail — mail@example.com"]
    view._search.setText("")
    assert len(_rows(view)) == 2


def test_add_flow_saves_and_refreshes(
    qtbot: QtBot, session: VaultSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = make_login(title="Added", username="new@example.com")
    monkeypatch.setattr(vault_view, "EntryFormDialog", _fake_form(entry))
    view = VaultView(session)
    qtbot.addWidget(view)
    view._add_flow()
    assert "Added — new@example.com" in _rows(view)
    assert [s.title for s in session.list_logins()] == ["Added"]


def test_invalid_entry_warns_and_keeps_dialog_open(
    qtbot: QtBot, session: VaultSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    real_add = vault_view.add_login

    def flaky_add(sess: VaultSession, entry) -> None:
        calls.append(1)
        if len(calls) == 1:
            raise ValueError("title must be 1-200 characters")
        real_add(sess, entry)

    monkeypatch.setattr(vault_view, "add_login", flaky_add)
    warned: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warned.append(a[2])))
    monkeypatch.setattr(vault_view, "EntryFormDialog", _fake_form(make_login(title="Valid")))
    view = VaultView(session)
    qtbot.addWidget(view)
    view._add_flow()
    assert len(calls) == 2  # the dialog was re-opened and the save retried
    assert any("title" in text for text in warned)
    assert [s.title for s in session.list_logins()] == ["Valid"]


def test_edit_flow_updates_and_records_history(
    qtbot: QtBot, session: VaultSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = make_login(title="Old Title")
    session.add(original)
    view = VaultView(session)
    qtbot.addWidget(view)
    _select_row(view, 0)
    monkeypatch.setattr(vault_view, "EntryFormDialog", _fake_form())
    view._edit_selected()
    assert [s.title for s in session.list_logins()] == ["Fresh Entry"]
    history = session.history(original.id)
    assert [item.title for item in history] == ["Old Title"]


def test_history_dialog_lists_previous_versions(
    qtbot: QtBot, session: VaultSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = make_login(title="Old Title")
    session.add(original)
    view = VaultView(session)
    qtbot.addWidget(view)
    _select_row(view, 0)
    monkeypatch.setattr(vault_view, "EntryFormDialog", _fake_form())
    view._edit_selected()
    captured: dict[str, object] = {}

    class FakeHistory:
        def __init__(self, title: str, entries) -> None:
            captured["title"] = title
            captured["entries"] = entries

        def exec(self):
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(vault_view, "HistoryDialog", FakeHistory)
    _select_row(view, 0)  # refresh after the edit cleared the selection
    view._show_history()
    assert captured["title"] == "Fresh Entry"
    assert [e.title for e in captured["entries"]] == ["Old Title"]


def test_delete_asks_then_moves_to_recycle_bin(
    qtbot: QtBot, session: VaultSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = make_login(title="Doomed")
    session.add(entry)
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    )
    view = VaultView(session)
    qtbot.addWidget(view)
    _select_row(view, 0)
    view._delete_flow()
    assert _rows(view) == []
    assert [s.title for s in session.list_logins()] == []
    assert session.get(entry.id).title == "Doomed"  # trashed, not gone


def test_delete_cancelled_keeps_entry(
    qtbot: QtBot, session: VaultSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    session.add(make_login(title="Keeper"))
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No)
    )
    view = VaultView(session)
    qtbot.addWidget(view)
    _select_row(view, 0)
    view._delete_flow()
    assert _rows(view) == ["Keeper — user@example.com"]


def test_password_never_reaches_the_log(
    qtbot: QtBot,
    session: VaultSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    canary = "CANARY-view-canary-1a2b"
    entry = make_login(title="Logged", password=SecretStr(canary))
    monkeypatch.setattr(vault_view, "EntryFormDialog", _fake_form(entry))
    view = VaultView(session)
    qtbot.addWidget(view)
    with caplog.at_level(logging.DEBUG, logger="personal_vault.ui"):
        view._add_flow()
    assert "saved entry" in caplog.text  # the logging path actually ran
    assert canary not in caplog.text
