"""Settings dialog (M2-07): every settings.json value, validated on save.

A file with a newer schema_version opens read-only: every control is
disabled and nothing can be saved over it. Invalid values are refused with
a message and the dialog stays open.
"""

from __future__ import annotations

from typing import cast

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QMessageBox,
    QSpinBox,
    QWidget,
)

from personal_vault.services import (
    settings_readonly,
    settings_values,
    update_settings,
)

_MAX_MINUTES = 10080  # a week
_MAX_SECONDS = 3600


class SettingsDialog(QDialog):
    """Edits settings.json; Save validates through services before closing."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self._readonly = settings_readonly()
        self._values = settings_values()

        self._idle_lock = self._spin("idle_lock_minutes", 1, _MAX_MINUTES)
        self._lock_on_sleep = self._check("lock_on_sleep")
        self._clipboard_clear = self._spin("clipboard_clear_seconds", 1, _MAX_SECONDS)
        self._backups_recent = self._spin("backups_keep_recent", 1, 999)
        self._backups_daily = self._spin("backups_keep_daily", 1, 999)
        self._sync_interval = self._spin("sync_interval_minutes", 1, _MAX_MINUTES)
        self._upload_quiet = self._spin("upload_quiet_seconds", 1, _MAX_SECONDS)

        generator = cast(dict[str, object], self._values.get("generator") or {})
        self._generator_length = QSpinBox()
        self._generator_length.setRange(4, 4096)
        length = generator.get("length")
        self._generator_length.setValue(length if isinstance(length, int) else 20)
        self._generator_flags: dict[str, QCheckBox] = {}
        for key, label in (
            ("upper", "Uppercase (A-Z)"),
            ("lower", "Lowercase (a-z)"),
            ("digits", "Digits (0-9)"),
            ("symbols", "Symbols (!@#$…)"),
            ("exclude_lookalikes", "Exclude look-alike characters"),
        ):
            flag = generator.get(key)
            box = QCheckBox(label)
            box.setChecked(flag if isinstance(flag, bool) else True)
            self._generator_flags[key] = box

        form = QFormLayout(self)
        form.addRow("Lock after idle (minutes)", self._idle_lock)
        form.addRow("Lock on system sleep", self._lock_on_sleep)
        form.addRow("Clear clipboard after (seconds)", self._clipboard_clear)
        form.addRow("Backups: recent copies to keep", self._backups_recent)
        form.addRow("Backups: daily copies to keep", self._backups_daily)
        form.addRow("Sync interval (minutes)", self._sync_interval)
        form.addRow("Upload quiet period (seconds)", self._upload_quiet)
        form.addRow("Generator: length", self._generator_length)
        form.addRow("Generator: classes", self._generator_flags["upper"])
        for key in ("lower", "digits", "symbols", "exclude_lookalikes"):
            form.addRow("", self._generator_flags[key])

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.accepted.connect(self._save)
        self._buttons.rejected.connect(self.reject)
        form.addRow(self._buttons)

        if self._readonly:
            note = QLabel(
                "This file has a newer schema version than this app understands; "
                "it is opened read-only and will not be overwritten."
            )
            note.setWordWrap(True)
            form.addRow(note)
            for control in self._all_controls():
                control.setEnabled(False)
            self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)

    def _spin(self, key: str, low: int, high: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(low, high)
        value = self._values.get(key)
        spin.setValue(value if isinstance(value, int) and not isinstance(value, bool) else low)
        return spin

    def _check(self, key: str) -> QCheckBox:
        box = QCheckBox()
        value = self._values.get(key)
        box.setChecked(bool(value))
        return box

    def _all_controls(self) -> list[QWidget]:
        return [
            self._idle_lock,
            self._lock_on_sleep,
            self._clipboard_clear,
            self._backups_recent,
            self._backups_daily,
            self._sync_interval,
            self._upload_quiet,
            self._generator_length,
            *self._generator_flags.values(),
        ]

    def _save(self) -> None:
        if self._readonly:
            return
        values: dict[str, object] = {
            "idle_lock_minutes": self._idle_lock.value(),
            "lock_on_sleep": self._lock_on_sleep.isChecked(),
            "clipboard_clear_seconds": self._clipboard_clear.value(),
            "backups_keep_recent": self._backups_recent.value(),
            "backups_keep_daily": self._backups_daily.value(),
            "sync_interval_minutes": self._sync_interval.value(),
            "upload_quiet_seconds": self._upload_quiet.value(),
            "generator": {
                "length": self._generator_length.value(),
                **{key: box.isChecked() for key, box in self._generator_flags.items()},
            },
        }
        try:
            update_settings(values)
        except ValueError as exc:
            QMessageBox.warning(self, "Personal Vault", str(exc))
            return  # dialog stays open with the fields intact
        self.accept()
