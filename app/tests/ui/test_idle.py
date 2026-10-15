"""M2-06: idle lock, manual lock, lock on sleep (pytest-qt)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fixtures.weak_vault import WEAK_PASSWORD, build_weak_vault
from personal_vault.core.vault import VaultSession
from personal_vault.services import Profile, profiles
from personal_vault.ui.app import App
from personal_vault.ui.idle import IdleMonitor
from personal_vault.ui.vault_view import VaultView
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot


@pytest.fixture
def monitor(qtbot: QtBot) -> IdleMonitor:
    widget = IdleMonitor(idle_minutes=1, lock_on_sleep=False)
    widget.stop()  # white-box ticks below; the wall clock must not interfere
    return widget


def test_simulated_inactivity_locks(monitor: IdleMonitor) -> None:
    spy = QSignalSpy(monitor.locked)
    for _ in range(60):
        monitor._tick()
    assert spy.count() == 1


def test_activity_resets_the_idle_timer(monitor: IdleMonitor) -> None:
    spy = QSignalSpy(monitor.locked)
    for _ in range(59):
        monitor._tick()
    monitor.activity()
    for _ in range(59):
        monitor._tick()
    assert spy.count() == 0
    monitor._tick()
    assert spy.count() == 1


def test_reported_sleep_locks_when_enabled(qtbot: QtBot) -> None:
    monitor = IdleMonitor(idle_minutes=1, lock_on_sleep=True)
    monitor.stop()
    spy = QSignalSpy(monitor.locked)
    monitor.report_system_sleep()
    assert spy.count() == 1


def test_reported_sleep_does_not_lock_when_disabled(qtbot: QtBot) -> None:
    monitor = IdleMonitor(idle_minutes=1, lock_on_sleep=False)
    monitor.stop()
    spy = QSignalSpy(monitor.locked)
    monitor.report_system_sleep()
    assert spy.count() == 0


def test_manual_lock_button_emits_locked(qtbot: QtBot, session: VaultSession) -> None:
    view = VaultView(session)
    qtbot.addWidget(view)
    spy = QSignalSpy(view.locked)
    view._lock_button.click()
    assert spy.count() == 1


@pytest.fixture
def session(tmp_path: Path) -> VaultSession:
    path = build_weak_vault(tmp_path / "vault.kdbx")
    return VaultSession.open(path, WEAK_PASSWORD, tmp_path / "backups")


def test_lock_drops_session_clears_clipboard_and_shows_unlock(
    qtbot: QtBot,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("PV_DATA_DIR", str(data_dir))
    profile = profiles().create("Test Profile")
    build_weak_vault(data_dir / "profiles" / profile.id / "vault.kdbx")

    window = App()
    qtbot.addWidget(window)
    window._on_opened(profile.id)
    unlock = window._unlock
    assert unlock is not None

    vault_path = data_dir / "profiles" / profile.id / "vault.kdbx"
    session = VaultSession.open(vault_path, WEAK_PASSWORD, tmp_path / "backups")
    window._on_unlocked(session)

    clipboard = QApplication.clipboard()
    clipboard.setText("CANARY-lock-clears-clipboard")
    assert window._session is session
    assert window._stack.currentWidget() is not unlock

    window._lock()

    assert window._session is None
    assert clipboard.text() == ""
    assert window._stack.currentWidget() is unlock


def test_unlock_screen_can_unlock_again_after_lock(
    qtbot: QtBot,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("PV_DATA_DIR", str(data_dir))
    profile: Profile = profiles().create("Test Profile")
    build_weak_vault(data_dir / "profiles" / profile.id / "vault.kdbx")

    window = App()
    qtbot.addWidget(window)
    window._on_opened(profile.id)
    unlock = window._unlock
    assert unlock is not None
    unlock._password.setText(WEAK_PASSWORD)
    unlock._try_unlock()  # real unlock through the window
    assert window._session is not None

    window._lock()
    assert window._session is None

    unlock._password.setText(WEAK_PASSWORD)
    unlock._try_unlock()
    assert window._session is not None
    assert window._stack.currentWidget() is not unlock
