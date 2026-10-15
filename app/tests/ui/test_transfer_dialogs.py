"""M2-08: export and import dialogs (pytest-qt)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fixtures.weak_vault import WEAK_PASSWORD, build_weak_vault, make_login
from personal_vault.core.vault import VaultSession, open_vault
from personal_vault.ui import transfer_dialogs
from personal_vault.ui.transfer_dialogs import CSV_CONFIRMATION, ExportDialog, ImportDialog
from PySide6.QtWidgets import QFileDialog, QMessageBox
from pytestqt.qtbot import QtBot


@pytest.fixture
def session(tmp_path: Path) -> VaultSession:
    path = build_weak_vault(tmp_path / "vault.kdbx")
    return VaultSession.open(path, WEAK_PASSWORD, tmp_path / "backups")


def _warnings(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    warned: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warned.append(a[2])))
    return warned


def test_kdbx_export_writes_an_openable_copy(
    qtbot: QtBot, session: VaultSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session.add(make_login(title="Export Me"))
    session.save()  # export reads the saved file
    target = tmp_path / "exported.kdbx"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(target), ""))
    )
    dialog = ExportDialog(session)
    qtbot.addWidget(dialog)
    dialog._new_password.setText("an-export-password-123")
    dialog._choose_path()  # fills _path from the monkeypatched file dialog
    dialog._export()
    assert dialog.result() == 1
    kp = open_vault(target, "an-export-password-123")
    assert [e.title for e in kp.entries] == ["Export Me"]


def test_csv_export_requires_master_password_and_typed_confirmation(
    qtbot: QtBot,
    session: VaultSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "exported.csv"
    calls: list[tuple[str, str]] = []

    def spy(sess: VaultSession, path: str | Path) -> None:
        calls.append((id(sess), str(path)))

    monkeypatch.setattr(transfer_dialogs, "export_csv", spy)
    warned = _warnings(monkeypatch)

    dialog = ExportDialog(session)
    qtbot.addWidget(dialog)
    dialog._csv_radio.setChecked(True)
    dialog._path.setText(str(target))

    dialog._master_password.setText("wrong-password-123")
    dialog._confirmation.setText(CSV_CONFIRMATION)
    dialog._export()
    assert calls == []
    assert any("Wrong master password" in text for text in warned)

    dialog._master_password.setText(WEAK_PASSWORD)
    dialog._confirmation.setText("nope")
    dialog._export()
    assert calls == []
    assert any("Type" in text for text in warned)

    dialog._confirmation.setText(CSV_CONFIRMATION)
    dialog._export()
    assert calls == [(id(session), str(target))]
    assert dialog.result() == 1


def test_csv_export_refuses_a_short_kdbx_password(
    qtbot: QtBot, session: VaultSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "exported.kdbx"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(target), ""))
    )
    warned = _warnings(monkeypatch)
    dialog = ExportDialog(session)
    qtbot.addWidget(dialog)
    dialog._new_password.setText("short")
    dialog._choose_path()  # fills _path from the monkeypatched file dialog
    dialog._export()
    assert not target.exists()
    assert any("12" in text for text in warned)
    assert dialog.result() == 0


def test_import_csv_dialog_imports_into_a_new_group(
    qtbot: QtBot, session: VaultSession, tmp_path: Path
) -> None:
    source = tmp_path / "in.csv"
    source.write_text(
        "title,username,password,urls\nImported,user@example.com,pw,https://example.com\n",
        encoding="utf-8",
    )
    dialog = ImportDialog(session)
    qtbot.addWidget(dialog)
    dialog._path.setText(str(source))
    dialog._import()
    assert dialog.result() == 1
    assert dialog.imported_count == 1
    groups = [g.name for g in session._open_kp.groups if g.name.startswith("Imported ")]
    assert len(groups) == 1


def test_import_dialog_shows_a_message_for_bad_files(
    qtbot: QtBot, session: VaultSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    warned = _warnings(monkeypatch)
    bad = tmp_path / "bad.csv"
    bad.write_text("not,a,header\n", encoding="utf-8")
    dialog = ImportDialog(session)
    qtbot.addWidget(dialog)
    dialog._path.setText(str(bad))
    dialog._import()
    assert dialog.result() == 0
    assert any("import failed" in text for text in warned)


def test_import_kdbx_dialog_refuses_a_wrong_password(
    qtbot: QtBot, session: VaultSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.kdbx"
    build_weak_vault(source)
    with VaultSession.open(source, WEAK_PASSWORD, tmp_path / "src-backups") as other:
        other.add(make_login(title="From Elsewhere"))
        other.save()
    warned = _warnings(monkeypatch)
    dialog = ImportDialog(session)
    qtbot.addWidget(dialog)
    dialog._path.setText(str(source))
    dialog._password.setText("not-the-password-123")
    dialog._import()
    assert dialog.result() == 0
    assert any("wrong master password" in text for text in warned)

    dialog._password.setText(WEAK_PASSWORD)
    dialog._import()
    assert dialog.result() == 1
    assert dialog.imported_count == 1
