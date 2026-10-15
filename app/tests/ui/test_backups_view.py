"""M2-08: the backups view (pytest-qt)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fixtures.weak_vault import WEAK_PASSWORD, build_weak_vault, make_login
from personal_vault.core.vault import VaultSession
from personal_vault.services import delete_login
from personal_vault.ui.backups_view import BackupsView
from PySide6.QtWidgets import QMessageBox
from pytestqt.qtbot import QtBot


@pytest.fixture
def session(tmp_path: Path) -> VaultSession:
    path = build_weak_vault(tmp_path / "vault.kdbx")
    return VaultSession.open(path, WEAK_PASSWORD, tmp_path / "backups")


def _rows(view: BackupsView) -> list[str]:
    return [view._list.item(i).text() for i in range(view._list.count())]


def test_lists_backups_newest_first(qtbot: QtBot, session: VaultSession) -> None:
    session.add(make_login(title="One"))
    session.save()
    session.add(make_login(title="Two"))
    session.save()
    view = BackupsView(session)
    qtbot.addWidget(view)
    rows = _rows(view)
    assert len(rows) == 2
    assert rows == sorted(rows, reverse=True)  # timestamp names sort newest first


def test_restore_after_confirmation_replaces_and_emits(
    qtbot: QtBot, session: VaultSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = make_login(title="One")
    session.add(first)
    session.save()  # backup #1: empty vault
    session.add(make_login(title="Two"))
    session.save()  # backup #2: contains "One"
    delete_login(session, first.id)
    session.save()  # backup #3: contains One and Two
    assert [s.title for s in session.list_logins()] == ["Two"]

    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    )
    view = BackupsView(session)
    qtbot.addWidget(view)
    restored: list[object] = []
    view.restored.connect(restored.append)
    view._list.setCurrentRow(1)  # newest first: [#3 One+Two, #2 One, #1 empty]
    view._restore()
    assert len(restored) == 1
    new_session = restored[0]
    assert new_session is not session
    assert [s.title for s in new_session.list_logins()] == ["One"]


def test_restore_cancelled_keeps_the_vault(
    qtbot: QtBot, session: VaultSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    session.add(make_login(title="One"))
    session.save()
    session.add(make_login(title="Two"))
    session.save()
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No)
    )
    view = BackupsView(session)
    qtbot.addWidget(view)
    restored: list[object] = []
    view.restored.connect(restored.append)
    view._list.setCurrentRow(0)
    view._restore()
    assert restored == []
    assert [s.title for s in session.list_logins()] == ["One", "Two"]
