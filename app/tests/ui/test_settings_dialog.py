"""M2-07: the settings dialog and generator defaults (pytest-qt)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from personal_vault.services import settings_values, update_settings
from personal_vault.ui.generator_dialog import GeneratorDialog
from personal_vault.ui.settings_dialog import SettingsDialog
from PySide6.QtWidgets import QDialogButtonBox, QMessageBox
from pytestqt.qtbot import QtBot


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PV_DATA_DIR", str(tmp_path / "data"))


def test_dialog_shows_defaults_on_first_run(qtbot: QtBot) -> None:
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    assert dialog._idle_lock.value() == 5
    assert dialog._lock_on_sleep.isChecked()
    assert dialog._clipboard_clear.value() == 30
    assert dialog._generator_length.value() == 20
    assert dialog._generator_flags["upper"].isChecked()


def test_saving_persists_and_reopening_shows_new_values(qtbot: QtBot) -> None:
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    dialog._idle_lock.setValue(12)
    dialog._clipboard_clear.setValue(45)
    dialog._generator_length.setValue(32)
    dialog._generator_flags["digits"].setChecked(False)
    dialog._save()
    assert dialog.result() == 1  # accepted and closed

    again = SettingsDialog()
    qtbot.addWidget(again)
    assert again._idle_lock.value() == 12
    assert again._clipboard_clear.value() == 45
    assert again._generator_length.value() == 32
    assert not again._generator_flags["digits"].isChecked()


def test_invalid_values_are_refused_with_a_message(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    warned: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warned.append(a[2])))
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    dialog._save()  # valid values; writes and closes
    assert warned == []
    assert dialog.result() == 1  # accepted

    dialog2 = SettingsDialog()
    qtbot.addWidget(dialog2)

    def refuse(_values: dict[str, object]) -> None:
        raise ValueError("idle_lock_minutes must be a positive integer")

    monkeypatch.setattr("personal_vault.ui.settings_dialog.update_settings", refuse)
    dialog2._save()
    assert any("idle_lock_minutes" in text for text in warned)
    assert dialog2.result() == 0  # still open


def test_core_refuses_zero_minutes_and_bad_generator_length() -> None:
    with pytest.raises(ValueError):
        update_settings({"idle_lock_minutes": 0})
    with pytest.raises(ValueError):
        update_settings({"generator": {"length": 3}})


def test_newer_schema_opens_read_only(qtbot: QtBot, tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir(parents=True)
    (data / "settings.json").write_text(
        json.dumps({"schema_version": 99, "idle_lock_minutes": 7}), encoding="utf-8"
    )
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    assert dialog._readonly
    assert dialog._idle_lock.value() == 7  # values still shown
    assert not dialog._idle_lock.isEnabled()
    assert not dialog._buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()


def test_generator_defaults_come_from_settings(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    update_settings(
        {
            "generator": {
                "length": 48,
                "upper": False,
                "lower": False,
                "digits": True,
                "symbols": False,
                "exclude_lookalikes": False,
            }
        }
    )
    dialog = GeneratorDialog()
    qtbot.addWidget(dialog)
    assert dialog._length.value() == 48
    assert dialog._digits.isChecked()
    assert not dialog._upper.isChecked()
    assert not dialog._lower.isChecked()
    assert not dialog._symbols.isChecked()
    assert not dialog._exclude.isChecked()
    assert set(dialog._preview.text()) <= set("0123456789")


def test_defaults_show_up_in_settings_values() -> None:
    values = settings_values()
    assert values["idle_lock_minutes"] == 5
    assert values["lock_on_sleep"] is True
    assert values["generator"] == {
        "length": 20,
        "upper": True,
        "lower": True,
        "digits": True,
        "symbols": True,
        "exclude_lookalikes": True,
    }
