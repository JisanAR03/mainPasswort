"""Idle lock, manual lock, lock on sleep ([S], M2-06).

An IdleMonitor counts seconds without user activity and emits ``locked``
after ``idle_lock_minutes``; the ActivityFilter feeds it every real user
event (mouse, keys, wheel) from the QApplication event stream.

Qt does not deliver system sleep/screen-lock events cross-platform, so
``report_system_sleep`` is the hook an OS-level event source calls when one
exists (manual test covers what the OS actually reports). It locks only when
``lock_on_sleep`` is on.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QTimer, Signal


class IdleMonitor(QObject):
    """Emits ``locked`` after idle_minutes without activity (also on sleep)."""

    locked = Signal()

    def __init__(
        self,
        idle_minutes: int,
        lock_on_sleep: bool,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._seconds_limit = max(1, idle_minutes) * 60
        self._lock_on_sleep = lock_on_sleep
        self._idle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def activity(self) -> None:
        """Any user activity resets the idle countdown."""
        self._idle = 0

    def report_system_sleep(self) -> None:
        """The OS reported sleep or screen lock; lock if lock_on_sleep is on."""
        if self._lock_on_sleep:
            self.locked.emit()

    def stop(self) -> None:
        self._timer.stop()

    def _tick(self) -> None:
        self._idle += 1
        if self._idle >= self._seconds_limit:
            self._idle = 0
            self.locked.emit()


class ActivityFilter(QObject):
    """Event filter that reports user activity to a monitor."""

    def __init__(self, monitor: IdleMonitor, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._monitor = monitor

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() in (
            QEvent.Type.MouseButtonPress,
            QEvent.Type.KeyPress,
            QEvent.Type.Wheel,
        ):
            self._monitor.activity()
        return False
