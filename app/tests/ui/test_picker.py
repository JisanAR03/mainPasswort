"""M2-01: profile picker (pytest-qt)."""

from __future__ import annotations

from pathlib import Path

import pytest
from personal_vault.services import profiles
from personal_vault.ui.picker import ProfilePicker
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QInputDialog, QMessageBox
from pytestqt.qtbot import QtBot


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PV_DATA_DIR", str(tmp_path / "data"))


def _names(picker: ProfilePicker) -> list[str]:
    return [picker._list.item(i).text() for i in range(picker._list.count())]


def test_empty_state_shows_hint(qtbot: QtBot) -> None:
    picker = ProfilePicker()
    qtbot.addWidget(picker)
    assert _names(picker) == []
    assert not picker._empty_label.isHidden()
    assert not picker._open_button.isEnabled()


def test_lists_existing_profiles(qtbot: QtBot) -> None:
    store = profiles()
    store.create("Work")
    store.create("Social Media")
    picker = ProfilePicker()
    qtbot.addWidget(picker)
    assert _names(picker) == ["Work", "Social Media"]
    assert picker._empty_label.isHidden()


def test_create_flow_adds_and_selects(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("School", True)))
    picker = ProfilePicker()
    qtbot.addWidget(picker)
    qtbot.mouseClick(picker._new_button, Qt.MouseButton.LeftButton)
    assert _names(picker) == ["School"]
    assert picker._list.currentItem().text() == "School"
    assert [p.display_name for p in profiles().list()] == ["School"]


def test_create_cancelled_adds_nothing(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("", False)))
    picker = ProfilePicker()
    qtbot.addWidget(picker)
    qtbot.mouseClick(picker._new_button, Qt.MouseButton.LeftButton)
    assert _names(picker) == []


def test_create_rejects_empty_name(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("   ", True)))
    warned: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warned.append(a[2])))
    picker = ProfilePicker()
    qtbot.addWidget(picker)
    qtbot.mouseClick(picker._new_button, Qt.MouseButton.LeftButton)
    assert _names(picker) == []
    assert warned  # the validation message was shown


def test_rename_keeps_profile_id(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    store = profiles()
    created = store.create("Old Name")
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("New Name", True)))
    picker = ProfilePicker()
    qtbot.addWidget(picker)
    picker._list.setCurrentRow(0)
    qtbot.mouseClick(picker._rename_button, Qt.MouseButton.LeftButton)
    assert _names(picker) == ["New Name"]
    (renamed,) = profiles().list()
    assert renamed.id == created.id  # files never move on rename


def test_delete_asks_then_removes(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    profiles().create("Doomed")
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    )
    picker = ProfilePicker()
    qtbot.addWidget(picker)
    picker._list.setCurrentRow(0)
    qtbot.mouseClick(picker._delete_button, Qt.MouseButton.LeftButton)
    assert _names(picker) == []
    assert profiles().list() == []


def test_delete_cancelled_keeps_profile(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    profiles().create("Keeper")
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No)
    )
    picker = ProfilePicker()
    qtbot.addWidget(picker)
    picker._list.setCurrentRow(0)
    qtbot.mouseClick(picker._delete_button, Qt.MouseButton.LeftButton)
    assert _names(picker) == ["Keeper"]


def test_open_emits_id_and_remembers_last_used(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = profiles().create("Personal")
    picker = ProfilePicker()
    qtbot.addWidget(picker)
    opened: list[str] = []
    picker.opened.connect(opened.append)
    picker._list.setCurrentRow(0)
    qtbot.mouseClick(picker._open_button, Qt.MouseButton.LeftButton)
    assert opened == [created.id]
    assert profiles().last_used() == created.id
