"""Generator dialog (M2-04): options, preview, regenerate, use this password.

The preview regenerates whenever an option changes and is masked until the
user asks to show it. Invalid options (no character class) disable both
buttons and the reason is shown. Nothing here ever logs a generated value.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QWidget,
)

from personal_vault.services import SecretStr, generate_password, generator_defaults


class GeneratorDialog(QDialog):
    """Generates a password; ``selected`` is set when the user accepts."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Generate password")
        self.selected: SecretStr | None = None
        self._password: SecretStr | None = None

        defaults = generator_defaults()
        length = defaults.get("length")

        self._length = QSpinBox()
        self._length.setRange(4, 4096)
        self._length.setValue(length if isinstance(length, int) else 20)
        self._length.valueChanged.connect(self._generate)

        self._upper = QCheckBox("Uppercase (A-Z)")
        self._lower = QCheckBox("Lowercase (a-z)")
        self._digits = QCheckBox("Digits (0-9)")
        self._symbols = QCheckBox("Symbols (!@#$…)")
        self._exclude = QCheckBox("Exclude look-alike characters (0 O o 1 l I |)")
        for box, key in (
            (self._upper, "upper"),
            (self._lower, "lower"),
            (self._digits, "digits"),
            (self._symbols, "symbols"),
            (self._exclude, "exclude_lookalikes"),
        ):
            flag = defaults.get(key)
            box.setChecked(flag if isinstance(flag, bool) else True)
            box.toggled.connect(self._generate)

        self._preview = QLineEdit()
        self._preview.setEchoMode(QLineEdit.EchoMode.Password)
        self._show = QCheckBox("Show password")
        self._show.toggled.connect(
            lambda visible: self._preview.setEchoMode(
                QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
            )
        )

        self._error = QLabel()
        self._error.setWordWrap(True)
        self._error.setVisible(False)

        self._regenerate = QPushButton("Regenerate")
        self._regenerate.clicked.connect(self._generate)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save
        )
        self._buttons.rejected.connect(self.reject)
        self._use = self._buttons.button(QDialogButtonBox.StandardButton.Save)
        self._use.setText("Use this password")
        self._use.clicked.connect(self.accept)

        form = QFormLayout(self)
        form.addRow("Length", self._length)
        form.addRow("Character classes", self._upper)
        form.addRow("", self._lower)
        form.addRow("", self._digits)
        form.addRow("", self._symbols)
        form.addRow("", self._exclude)
        preview_row = QHBoxLayout()
        preview_row.addWidget(self._preview)
        preview_row.addWidget(self._show)
        form.addRow("Preview", preview_row)
        form.addRow("", self._error)
        form.addRow(self._regenerate, self._buttons)

        self._generate()

    def _generate(self) -> None:
        try:
            self._password = generate_password(
                self._length.value(),
                upper=self._upper.isChecked(),
                lower=self._lower.isChecked(),
                digits=self._digits.isChecked(),
                symbols=self._symbols.isChecked(),
                exclude_lookalikes=self._exclude.isChecked(),
            )
        except ValueError as exc:
            self._password = None
            self._preview.clear()
            self._error.setText(str(exc))
            self._error.setVisible(True)
            self._regenerate.setEnabled(False)
            self._use.setEnabled(False)
            return
        self._preview.setText(self._password.reveal())
        self._error.setVisible(False)
        self._regenerate.setEnabled(True)
        self._use.setEnabled(True)

    def accept(self) -> None:
        if self._password is not None:
            self.selected = self._password
        super().accept()
