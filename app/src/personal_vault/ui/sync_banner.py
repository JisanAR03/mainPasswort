"""M5-05: the conflict banner, and the three ways out of one.

Showing the banner changes nothing: no upload, no adoption, no deletion
happens until the owner clicks one of the three buttons, and each button is
the sync layer's own method (keep mine = upload, take theirs = adopt, open
both = look at the kept copy). While a conflict stands, the engine neither
uploads nor adopts anything.

The banner is deliberately ignorant of the sync internals: it gets three
callables and reports what they answered.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


@dataclass(frozen=True)
class SyncOutcome:
    """What a sync action reported: a sentence, and whether it worked."""

    ok: bool
    message: str
    adopted: bool = False  # the file on disk was replaced: the vault must reload


@dataclass(frozen=True)
class ConflictActions:
    """The three buttons' work; services.py supplies the real callables."""

    keep_mine: Callable[[], SyncOutcome]
    take_theirs: Callable[[], SyncOutcome]
    open_theirs: Callable[[Path], None]


def _when(value: object) -> str:
    """The detection time in words, or whatever the state file said."""
    if not isinstance(value, str):
        return "an unknown time"
    try:
        return datetime.fromisoformat(value).astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return value


class SyncBanner(QWidget):
    """The conflict banner: what happened, when, and the three choices."""

    resolved = Signal(object)  # a SyncOutcome that ended the conflict

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._actions: ConflictActions | None = None
        self._kept_path: Path | None = None

        self._heading_label = QLabel("Both copies changed since the last sync.")
        self._heading_label.setStyleSheet("font-weight: bold")
        self._detail_label = QLabel()
        self._detail_label.setWordWrap(True)
        self._status_label = QLabel()
        self._status_label.setWordWrap(True)

        self.keep_button = QPushButton("Keep mine")
        self.take_button = QPushButton("Take theirs")
        self.open_button = QPushButton("Open both")
        self.keep_button.clicked.connect(lambda: self._resolve("keep_mine"))
        self.take_button.clicked.connect(lambda: self._resolve("take_theirs"))
        self.open_button.clicked.connect(self._open_theirs)

        buttons = QHBoxLayout()
        for button in (self.keep_button, self.take_button, self.open_button):
            buttons.addWidget(button)

        layout = QVBoxLayout(self)
        layout.addWidget(self._heading_label)
        layout.addWidget(self._detail_label)
        layout.addLayout(buttons)
        layout.addWidget(self._status_label)
        self.hide()

    # --- what the banner is saying (the status line reads these too) --------

    @property
    def heading(self) -> str:
        return self._heading_label.text()

    @property
    def detail(self) -> str:
        return self._detail_label.text()

    @property
    def status(self) -> str:
        return self._status_label.text()

    def show_conflict(self, conflict: Mapping[str, object], actions: ConflictActions) -> None:
        """Put the banner up for a conflict the state file recorded."""
        self._actions = actions
        kept = conflict.get("kept_path")
        self._kept_path = Path(str(kept)) if kept else None
        where = f" at {self._kept_path.name}" if self._kept_path else ""
        when = _when(conflict.get("detected_at"))
        self._detail_label.setText(
            f"Google Drive's copy was kept{where} · detected {when}. "
            "Nothing has been changed on either side yet."
        )
        self._status_label.clear()
        self._set_buttons_enabled(True)
        self.show()

    def clear(self) -> None:
        """The conflict is over: take the banner away."""
        self._actions = None
        self._kept_path = None
        self.hide()

    # --- the three choices --------------------------------------------------

    def _resolve(self, which: str) -> None:
        if self._actions is None:
            return
        action = self._actions.keep_mine if which == "keep_mine" else self._actions.take_theirs
        self._set_buttons_enabled(False)
        try:
            outcome = action()
        except Exception as exc:  # noqa: BLE001 — a click must report, never crash
            self._status_label.setText(f"The conflict could not be resolved: {exc}")
            self._set_buttons_enabled(True)
            return
        if not outcome.ok:
            self._status_label.setText(outcome.message)
            self._set_buttons_enabled(True)
            return
        self.clear()
        self.resolved.emit(outcome)

    def _open_theirs(self) -> None:
        actions = self._actions
        if actions is None or self._kept_path is None:
            return
        try:
            actions.open_theirs(self._kept_path)
        except Exception as exc:  # noqa: BLE001 — the copy may not open at all
            self._status_label.setText(str(exc))
            return
        self._status_label.setText(
            "That copy is open beside yours, read-only. The conflict is still here: "
            "choose Keep mine or Take theirs when you are done."
        )

    def _set_buttons_enabled(self, enabled: bool) -> None:
        for button in (self.keep_button, self.take_button, self.open_button):
            button.setEnabled(enabled)
