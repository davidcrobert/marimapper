"""Compact panel for 3D Placement mode controls and status."""

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QHBoxLayout,
    QGroupBox,
    QListWidget,
    QListWidgetItem,
)


class PlacementPanel(QWidget):
    """Right-side panel for placement mode (selection/status/commit stubs)."""

    exit_requested = pyqtSignal()
    commit_requested = pyqtSignal()
    discard_requested = pyqtSignal()
    problem_selected = pyqtSignal(int)
    next_problem_requested = pyqtSignal(bool)  # True = forward, False = backward
    place_problem_requested = pyqtSignal(int)
    interpolate_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dirty = False
        self.selected_led: int | None = None
        self.selected_position: tuple[float, float, float] | None = None
        self.problem_ids: list[int] = []
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

        # Problem list
        problems_group = QGroupBox("Problem LEDs")
        problems_layout = QVBoxLayout()
        self.problem_hint = QLabel("Unreconstructed / pending LEDs")
        self.problem_hint.setStyleSheet("color: #555; font-size: 11px;")
        problems_layout.addWidget(self.problem_hint)
        self.problem_list = QListWidget()
        self.problem_list.itemClicked.connect(self._on_problem_clicked)
        problems_layout.addWidget(self.problem_list)

        nav_row = QHBoxLayout()
        self.prev_problem_btn = QPushButton("Prev")
        self.prev_problem_btn.clicked.connect(lambda: self.next_problem_requested.emit(False))
        self.place_problem_btn = QPushButton("Place")
        self.place_problem_btn.clicked.connect(self._emit_place_problem)
        self.next_problem_btn = QPushButton("Next")
        self.next_problem_btn.clicked.connect(lambda: self.next_problem_requested.emit(True))
        nav_row.addWidget(self.prev_problem_btn)
        nav_row.addWidget(self.place_problem_btn)
        nav_row.addWidget(self.next_problem_btn)
        nav_row.addStretch()
        problems_layout.addLayout(nav_row)

        problems_group.setLayout(problems_layout)
        layout.addWidget(problems_group)

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

        self.interpolate_button = QPushButton("Interpolate all problem LEDs as light strip")
        self.interpolate_button.setMinimumHeight(36)
        self.interpolate_button.clicked.connect(self.interpolate_requested.emit)
        layout.addWidget(self.interpolate_button)

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

    def set_problem_ids(self, ids: list[int]):
        """Populate the problem LEDs list."""
        self.problem_ids = ids or []
        self.problem_list.blockSignals(True)
        self.problem_list.clear()
        for led_id in self.problem_ids:
            item = QListWidgetItem(f"LED {led_id}")
            item.setData(0, led_id)
            self.problem_list.addItem(item)
        self.problem_list.blockSignals(False)
        self.problem_hint.setText(f"Unreconstructed / pending LEDs ({len(self.problem_ids)})")
        self.prev_problem_btn.setEnabled(len(self.problem_ids) > 0)
        self.next_problem_btn.setEnabled(len(self.problem_ids) > 0)

    def select_problem_id(self, led_id: int | None):
        """Highlight a problem entry when selected elsewhere."""
        if led_id is None or not self.problem_ids:
            self.problem_list.clearSelection()
            return
        for i in range(self.problem_list.count()):
            item = self.problem_list.item(i)
            if item.data(0) == led_id:
                self.problem_list.blockSignals(True)
                self.problem_list.setCurrentItem(item)
                self.problem_list.blockSignals(False)
                return
        self.problem_list.clearSelection()

    def _on_problem_clicked(self, item: QListWidgetItem):
        led_id = item.data(0)
        try:
            led_id_int = int(led_id)
            self.problem_selected.emit(led_id_int)
        except Exception:
            pass

    def _emit_place_problem(self):
        if self.problem_list.currentItem() is None:
            return
        led_id = self.problem_list.currentItem().data(0)
        try:
            led_id_int = int(led_id)
            self.place_problem_requested.emit(led_id_int)
        except Exception:
            pass
