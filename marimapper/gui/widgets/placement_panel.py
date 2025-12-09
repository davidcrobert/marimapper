"""Compact panel for 3D Placement mode controls and status."""

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout, QGroupBox


class PlacementPanel(QWidget):
    """Right-side panel for placement mode (selection/status/commit stubs)."""

    exit_requested = pyqtSignal()
    commit_requested = pyqtSignal()
    discard_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dirty = False
        self.selected_led: int | None = None
        self.selected_position: tuple[float, float, float] | None = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)

        title = QLabel("Placement Mode")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)

        self.status_label = QLabel("Focused placement workflow is active.")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        # Selection summary
        selection_group = QGroupBox("Selection")
        selection_layout = QVBoxLayout()
        self.selection_label = QLabel("No LED selected")
        self.selection_label.setWordWrap(True)
        selection_layout.addWidget(self.selection_label)
        selection_group.setLayout(selection_layout)
        layout.addWidget(selection_group)

        # Actions
        actions_row = QHBoxLayout()
        self.commit_button = QPushButton("Commit placement")
        self.commit_button.clicked.connect(self.commit_requested.emit)
        actions_row.addWidget(self.commit_button)

        self.discard_button = QPushButton("Discard changes")
        self.discard_button.clicked.connect(self.discard_requested.emit)
        actions_row.addWidget(self.discard_button)
        layout.addLayout(actions_row)

        self.exit_button = QPushButton("Exit placement")
        self.exit_button.clicked.connect(self.exit_requested.emit)
        layout.addWidget(self.exit_button)

        # Quick hint
        hint = QLabel("Tip: Esc exits placement; click a point to select it. Drag to orbit; right-drag to pan.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #555; font-size: 11px;")
        layout.addWidget(hint)

        layout.addStretch()
        self.setLayout(layout)

    def set_selected_led(self, led_id: int | None, position: tuple[float, float, float] | None = None):
        """Update selection summary text."""
        self.selected_led = led_id
        self.selected_position = position
        if led_id is None:
            self.selection_label.setText("No LED selected")
        else:
            pos_str = f"({position[0]:.2f}, {position[1]:.2f}, {position[2]:.2f})" if position else "(unknown)"
            self.selection_label.setText(f"LED {led_id} selected\nPos: {pos_str}")

    def set_dirty(self, dirty: bool):
        """Toggle unsaved/dirty indicator."""
        self._dirty = dirty
        if dirty:
            self.status_label.setText("Unsaved placement edits. Commit or discard when ready.")
            self.status_label.setStyleSheet("color: #b45309;")
        else:
            self.status_label.setText("Focused placement workflow is active.")
            self.status_label.setStyleSheet("")
