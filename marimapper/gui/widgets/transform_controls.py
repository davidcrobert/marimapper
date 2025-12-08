"""
Transform controls placeholder widget for 3D view.

Provides basic translation / rotation / scale inputs (no functionality yet).
"""

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QGroupBox,
    QGridLayout,
    QLabel,
    QDoubleSpinBox,
    QPushButton,
    QCheckBox,
    QHBoxLayout,
)
from PyQt6.QtCore import pyqtSignal


class TransformControlsWidget(QWidget):
    """UI-only transform controls for the 3D view."""

    transform_changed = pyqtSignal(dict)
    save_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        layout.addWidget(self._build_compact_matrix())
        self.save_button = QPushButton("Save Transformed Cloud")
        self.save_button.clicked.connect(self.save_requested.emit)
        layout.addWidget(self.save_button)

        layout.addStretch()

        self.setLayout(layout)

    def _build_compact_matrix(self):
        group = QGroupBox("Transform")
        grid = QGridLayout()

        # Headers
        grid.addWidget(QLabel(""), 0, 0)
        grid.addWidget(QLabel("X"), 0, 1)
        grid.addWidget(QLabel("Y"), 0, 2)
        grid.addWidget(QLabel("Z"), 0, 3)

        # Translation row
        grid.addWidget(QLabel("Translate"), 1, 0)
        self.tx = self._spinbox(-1000.0, 1000.0, 0.1, 0.0, self._emit_transform)
        self.ty = self._spinbox(-1000.0, 1000.0, 0.1, 0.0, self._emit_transform)
        self.tz = self._spinbox(-1000.0, 1000.0, 0.1, 0.0, self._emit_transform)
        grid.addWidget(self.tx, 1, 1)
        grid.addWidget(self.ty, 1, 2)
        grid.addWidget(self.tz, 1, 3)

        # Rotation row
        grid.addWidget(QLabel("Rotate"), 2, 0)
        self.rx = self._spinbox(-180.0, 180.0, 1.0, 0.0, self._emit_transform)
        self.ry = self._spinbox(-180.0, 180.0, 1.0, 0.0, self._emit_transform)
        self.rz = self._spinbox(-180.0, 180.0, 1.0, 0.0, self._emit_transform)
        grid.addWidget(self.rx, 2, 1)
        grid.addWidget(self.ry, 2, 2)
        grid.addWidget(self.rz, 2, 3)

        # Scale row
        grid.addWidget(QLabel("Scale"), 3, 0)
        self.sx = self._spinbox(0.01, 10.0, 0.01, 1.0, lambda v: self._on_scale_changed(v, self.sx))
        self.sy = self._spinbox(0.01, 10.0, 0.01, 1.0, lambda v: self._on_scale_changed(v, self.sy))
        self.sz = self._spinbox(0.01, 10.0, 0.01, 1.0, lambda v: self._on_scale_changed(v, self.sz))
        grid.addWidget(self.sx, 3, 1)
        grid.addWidget(self.sy, 3, 2)
        grid.addWidget(self.sz, 3, 3)

        # Lock row
        lock_row = QHBoxLayout()
        lock_row.addWidget(QLabel("Lock scale ratio"))
        self.lock_scale_checkbox = QCheckBox()
        self.lock_scale_checkbox.setChecked(False)
        self.lock_scale_checkbox.toggled.connect(self._on_lock_toggled)
        lock_row.addWidget(self.lock_scale_checkbox)
        lock_row.addStretch()
        grid.addLayout(lock_row, 4, 0, 1, 4)

        group.setLayout(grid)
        return group

    def _spinbox(self, minimum: float, maximum: float, step: float, default: float, on_change=None):
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setSingleStep(step)
        spin.setDecimals(3)
        spin.setValue(default)
        spin.setKeyboardTracking(False)
        if on_change is not None:
            spin.valueChanged.connect(on_change)
        return spin

    def _on_scale_changed(self, value: float, source_spin: QDoubleSpinBox):
        if self.lock_scale_checkbox.isChecked():
            for spin in (self.sx, self.sy, self.sz):
                if spin is source_spin:
                    continue
                spin.blockSignals(True)
                spin.setValue(value)
                spin.blockSignals(False)
        self._emit_transform()

    def _on_lock_toggled(self, locked: bool):
        if locked:
            # unify scales to current X value when locking
            value = self.sx.value()
            for spin in (self.sy, self.sz):
                spin.blockSignals(True)
                spin.setValue(value)
                spin.blockSignals(False)
            self._emit_transform()

    def _emit_transform(self):
        transform = {
            "translation": (self.tx.value(), self.ty.value(), self.tz.value()),
            "rotation": (self.rx.value(), self.ry.value(), self.rz.value()),
            "scale": (self.sx.value(), self.sy.value(), self.sz.value()),
        }
        self.transform_changed.emit(transform)

    def set_transform(self, transform: dict):
        """Populate the UI from a transform dictionary."""
        # Avoid recursive signals while updating the UI.
        spins = (
            (self.tx, transform.get("translation", (0, 0, 0))[0]),
            (self.ty, transform.get("translation", (0, 0, 0))[1]),
            (self.tz, transform.get("translation", (0, 0, 0))[2]),
            (self.rx, transform.get("rotation", (0, 0, 0))[0]),
            (self.ry, transform.get("rotation", (0, 0, 0))[1]),
            (self.rz, transform.get("rotation", (0, 0, 0))[2]),
            (self.sx, transform.get("scale", (1, 1, 1))[0]),
            (self.sy, transform.get("scale", (1, 1, 1))[1]),
            (self.sz, transform.get("scale", (1, 1, 1))[2]),
        )
        for spin, value in spins:
            spin.blockSignals(True)
            spin.setValue(float(value))
            spin.blockSignals(False)

        # If locked, keep all scale values in sync (use X as source).
        if self.lock_scale_checkbox.isChecked():
            value = self.sx.value()
            for spin in (self.sy, self.sz):
                spin.blockSignals(True)
                spin.setValue(value)
                spin.blockSignals(False)

        self._emit_transform()
