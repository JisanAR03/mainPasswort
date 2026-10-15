"""M2-02: unlock screen (pytest-qt)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fixtures.weak_vault import WEAK_PASSWORD, build_weak_vault
from personal_vault.core.vault import VaultSession
from personal_vault.services import Profile, profiles
from personal_vault.ui.unlock import UnlockWindow
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QLineEdit, QMessageBox
from pytestqt.qtbot import QtBot


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PV_DATA_DIR", str(tmp_path / "data"))


@pytest.fixture
def profile_with_vault(tmp_path: Path) -> Profile:
    profile = profiles().create("Personal")
    folder = Path(os.environ["PV_DATA_DIR"]) / "profiles" / profile.id
    build_weak_vault(folder / "vault.kdbx")
    return profile


def _warnings(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: shown.append(a[2])))
    return shown


def test_unlock_disabled_until_twelve_characters(qtbot: QtBot, profile_with_vault: Profile) -> None:
    window = UnlockWindow(profile_with_vault)
    qtbot.addWidget(window)
    assert not window._unlock_button.isEnabled()
    window._password.setText("short")
    assert not window._unlock_button.isEnabled()
    window._password.setText("long-enough-password")
    assert window._unlock_button.isEnabled()


def test_hint_recommends_a_passphrase(qtbot: QtBot, profile_with_vault: Profile) -> None:
    window = UnlockWindow(profile_with_vault)
    qtbot.addWidget(window)
    texts = [label.text() for label in window.findChildren(QLabel)]
    assert any("passphrase" in text.lower() for text in texts)


def test_password_field_is_masked(qtbot: QtBot, profile_with_vault: Profile) -> None:
    window = UnlockWindow(profile_with_vault)
    qtbot.addWidget(window)
    assert window._password.echoMode() == QLineEdit.EchoMode.Password


def test_wrong_password_shows_message_and_clears(
    qtbot: QtBot, profile_with_vault: Profile, monkeypatch: pytest.MonkeyPatch
) -> None:
    shown = _warnings(monkeypatch)
    window = UnlockWindow(profile_with_vault)
    qtbot.addWidget(window)
    opened: list[object] = []
    window.unlocked.connect(opened.append)
    window._password.setText("wrong-master-password")
    qtbot.mouseClick(window._unlock_button, Qt.MouseButton.LeftButton)
    assert any("Wrong master password" in text for text in shown)
    assert window._password.text() == ""
    assert opened == []


def test_damaged_vault_shows_message_without_crashing(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shown = _warnings(monkeypatch)
    profile = profiles().create("Personal")
    folder = Path(os.environ["PV_DATA_DIR"]) / "profiles" / profile.id
    folder.mkdir(parents=True)
    (folder / "vault.kdbx").write_bytes(b"garbage")
    window = UnlockWindow(profile)
    qtbot.addWidget(window)
    window._password.setText(WEAK_PASSWORD)
    qtbot.mouseClick(window._unlock_button, Qt.MouseButton.LeftButton)
    assert any("damaged" in text for text in shown)
    assert window._password.text() == ""


def test_correct_password_unlocks_and_clears(qtbot: QtBot, profile_with_vault: Profile) -> None:
    window = UnlockWindow(profile_with_vault)
    qtbot.addWidget(window)
    opened: list[object] = []
    window.unlocked.connect(opened.append)
    window._password.setText(WEAK_PASSWORD)
    qtbot.mouseClick(window._unlock_button, Qt.MouseButton.LeftButton)
    assert len(opened) == 1
    assert isinstance(opened[0], VaultSession)
    opened[0].close()
    assert window._password.text() == ""
