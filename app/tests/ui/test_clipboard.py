"""M2-05: clipboard copy with auto-clear (pytest-qt)."""

from __future__ import annotations

import logging

import pytest
from personal_vault.ui.clipboard import ClipboardGuard
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

CANARY = "CANARY-clipboard-1a2b"


@pytest.fixture
def guard(qtbot: QtBot) -> ClipboardGuard:
    QApplication.clipboard().clear()
    return ClipboardGuard(clear_seconds=1)


def test_copy_sets_clipboard_and_starts_timer(guard: ClipboardGuard) -> None:
    guard.copy(CANARY)
    assert QApplication.clipboard().text() == CANARY
    assert guard.active()


def test_timer_clears_the_clipboard(guard: ClipboardGuard) -> None:
    guard.copy(CANARY)
    QTest.qWait(1100)
    assert QApplication.clipboard().text() == ""
    assert not guard.active()


def test_second_copy_replaces_value_and_restarts_the_timer(guard: ClipboardGuard) -> None:
    guard.copy("first value")
    QTest.qWait(600)
    guard.copy("second value")
    QTest.qWait(600)
    assert QApplication.clipboard().text() == "second value"  # timer restarted
    QTest.qWait(600)
    assert QApplication.clipboard().text() == ""


def test_explicit_clear_stops_timer_and_empties(guard: ClipboardGuard) -> None:
    guard.copy(CANARY)
    guard.clear()
    assert QApplication.clipboard().text() == ""
    assert not guard.active()
    QTest.qWait(1100)  # the stopped timer must not fire again
    assert QApplication.clipboard().text() == ""


def test_copying_an_empty_password_does_nothing(guard: ClipboardGuard) -> None:
    QApplication.clipboard().setText("sentinel")
    guard.copy("")
    assert QApplication.clipboard().text() == "sentinel"
    assert not guard.active()


def test_value_never_reaches_the_log(
    guard: ClipboardGuard, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG, logger="personal_vault.ui"):
        guard.copy(CANARY)
        QTest.qWait(1100)
    assert CANARY not in caplog.text
