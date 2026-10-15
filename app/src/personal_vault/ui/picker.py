"""Profile picker (M2-01): list, create, rename, delete and open a profile."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from personal_vault.services import profiles


class ProfilePicker(QWidget):
    """Lists profiles and edits the profile list through services."""

    opened = Signal(str)  # profile id

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = profiles()

        self._empty_label = QLabel("No profiles yet. Create one to get started.")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(self._open_selected)
        self._list.currentItemChanged.connect(lambda *_: self._update_buttons())

        self._new_button = QPushButton("New profile")
        self._rename_button = QPushButton("Rename")
        self._delete_button = QPushButton("Delete")
        self._open_button = QPushButton("Open")
        self._new_button.clicked.connect(self._create)
        self._rename_button.clicked.connect(self._rename_selected)
        self._delete_button.clicked.connect(self._delete_selected)
        self._open_button.clicked.connect(self._open_selected)

        buttons = QHBoxLayout()
        for button in (
            self._new_button,
            self._rename_button,
            self._delete_button,
            self._open_button,
        ):
            buttons.addWidget(button)

        layout = QVBoxLayout(self)
        layout.addWidget(self._empty_label)
        layout.addWidget(self._list)
        layout.addLayout(buttons)
        self._refresh()

    def _refresh(self) -> None:
        self._list.clear()
        for profile in self._store.list():
            item = QListWidgetItem(profile.display_name)
            item.setData(Qt.ItemDataRole.UserRole, profile.id)
            self._list.addItem(item)
        self._empty_label.setVisible(self._list.count() == 0)
        self._update_buttons()

    def _update_buttons(self) -> None:
        has_selection = self._list.currentItem() is not None
        self._rename_button.setEnabled(has_selection)
        self._delete_button.setEnabled(has_selection)
        self._open_button.setEnabled(has_selection)

    def _selected_id(self) -> str | None:
        item = self._list.currentItem()
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return str(value) if value is not None else None

    def _warn(self, message: str) -> None:
        QMessageBox.warning(self, "Personal Vault", message)

    def _create(self) -> None:
        name, ok = QInputDialog.getText(self, "New profile", "Profile name:")
        if not ok:
            return
        try:
            profile = self._store.create(name)
        except ValueError as exc:
            self._warn(str(exc))
            return
        self._refresh()
        self._select(profile.id)

    def _rename_selected(self) -> None:
        profile_id = self._selected_id()
        if profile_id is None:
            return
        current = self._display_name(profile_id)
        name, ok = QInputDialog.getText(self, "Rename profile", "Profile name:", text=current)
        if not ok:
            return
        try:
            self._store.rename(profile_id, name)
        except ValueError as exc:
            self._warn(str(exc))
            return
        self._refresh()
        self._select(profile_id)

    def _delete_selected(self) -> None:
        profile_id = self._selected_id()
        if profile_id is None:
            return
        answer = QMessageBox.question(
            self,
            "Delete profile",
            f'Delete profile "{self._display_name(profile_id)}"? Its vault files stay on disk.',
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._store.delete(profile_id)
        self._refresh()

    def _open_selected(self) -> None:
        profile_id = self._selected_id()
        if profile_id is None:
            return
        self._store.set_last_used(profile_id)
        self.opened.emit(profile_id)

    def _display_name(self, profile_id: str) -> str:
        for profile in self._store.list():
            if profile.id == profile_id:
                return profile.display_name
        return ""

    def _select(self, profile_id: str) -> None:
        for row in range(self._list.count()):
            item = self._list.item(row)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == profile_id:
                self._list.setCurrentItem(item)
                return
