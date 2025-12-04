"""
LED detection status table widget for MariMapper GUI.

Displays the reconstruction status of each LED with color-coded rows.
"""

import math
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView, QLabel
from PyQt6.QtCore import Qt, pyqtSlot, pyqtSignal
from PyQt6.QtGui import QColor


class StatusTable(QWidget):
    """Widget displaying LED reconstruction status in a table."""

    # Signals
    led_toggle_requested = pyqtSignal(int, bool)  # (led_id, turn_on)

    # Color scheme for LED states
    COLORS = {
        "RECONSTRUCTED": QColor(144, 238, 144),      # Light green
        "INTERPOLATED": QColor(173, 216, 230),       # Light blue
        "MERGED": QColor(173, 216, 230),             # Light blue
        "DETECTED": QColor(255, 255, 153),           # Light yellow
        "UNRECONSTRUCTABLE": QColor(255, 182, 193),  # Light red/pink
        "NONE": QColor(240, 240, 240),               # Light gray
    }

    # Short labels to keep cells compact
    ABBREVIATIONS = {
        "RECONSTRUCTED": "R",
        "INTERPOLATED": "I",
        "MERGED": "M",
        "DETECTED": "D",
        "UNRECONSTRUCTABLE": "U",
        "NONE": "-",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.led_data = {}  # LED ID -> LEDInfo (enum)
        self.sorted_ids: list[int] = []
        self.manual_on_leds: set[int] = set()
        self.pairs_per_row = 10  # Each LED occupies two columns (ID + status)
        self.columns_configured = False  # Track if columns have been set up
        self.init_ui()

    def init_ui(self):
        """Initialize the user interface."""
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        # Summary label shows totals by status at a glance
        self.summary_label = QLabel("Totals: (waiting for data)")
        self.summary_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.summary_label)

        # Compact legend showing status colors and names
        legend_layout = QHBoxLayout()
        legend_layout.setSpacing(3)
        legend_layout.setContentsMargins(4, 2, 4, 2)

        status_info = [
            ("R", "RECONSTRUCTED", "Reconstructed", "3D position found via SfM"),
            ("I", "INTERPOLATED", "Interpolated", "Position calculated between detected LEDs"),
            ("M", "MERGED", "Merged", "Duplicate detections merged"),
            ("D", "DETECTED", "Detected", "Seen in 2D, waiting for 3D reconstruction"),
            ("U", "UNRECONSTRUCTABLE", "Unreconstructable", "Cannot reconstruct 3D position"),
            ("-", "NONE", "None", "Not yet detected"),
        ]

        for abbr, status, display_name, description in status_info:
            # Color square
            color_label = QLabel()
            color_label.setFixedSize(10, 10)
            color_label.setStyleSheet(f"background-color: {self.COLORS[status].name()}; border: 1px solid #999;")
            color_label.setToolTip(description)

            # Full name with abbreviation in brackets
            text_label = QLabel(f"{display_name} ({abbr})")
            text_label.setToolTip(description)
            text_label.setStyleSheet("font-size: 9px;")

            legend_layout.addWidget(color_label)
            legend_layout.addWidget(text_label)
            legend_layout.addSpacing(6)

        legend_layout.addStretch()

        # Wrap in a widget for styling
        legend_widget = QWidget()
        legend_widget.setLayout(legend_layout)
        legend_widget.setStyleSheet("QWidget { background-color: #f5f5f5; border: 1px solid #ccc; border-radius: 3px; }")
        legend_widget.setMaximumHeight(22)

        layout.addWidget(legend_widget)

        # Create table
        self.table = QTableWidget()
        # Configure table appearance
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectItems)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(14)  # Smaller rows to fit more

        self._configure_columns()

        layout.addWidget(self.table)
        layout.setStretch(1, 1)  # Let table grab vertical space
        self.setLayout(layout)

    def _configure_columns(self):
        """Configure the table to show multiple LED columns per row."""
        column_count = self.pairs_per_row * 2
        self.table.setColumnCount(column_count)

        headers = []
        for i in range(self.pairs_per_row):
            headers.extend([f"ID{i+1}", "St"])
        self.table.setHorizontalHeaderLabels(headers)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)

        # Narrow columns to fit more LEDs across
        for i in range(column_count):
            if i % 2 == 0:  # ID column
                self.table.setColumnWidth(i, 8)
            else:  # Status column
                self.table.setColumnWidth(i, 8)

        # Reduce row height and font size for denser display
        self.table.verticalHeader().setDefaultSectionSize(12)
        font = self.table.font()
        font.setPointSize(max(font.pointSize() - 4, 6))
        self.table.setFont(font)

        # Only connect signal once
        if not self.columns_configured:
            self.table.cellClicked.connect(self._on_cell_clicked)
            self.columns_configured = True

    def _status_name(self, led_info) -> str:
        """Return the status name string for a LEDInfo-like object."""
        if hasattr(led_info, "name"):
            return led_info.name
        if hasattr(led_info, "type") and hasattr(led_info.type, "name"):
            return led_info.type.name
        return str(led_info)

    def _abbreviation(self, status: str) -> str:
        """Return short label for a status name."""
        return self.ABBREVIATIONS.get(status, status[:2].upper())

    @pyqtSlot(dict)
    def update_led_info(self, led_info_dict: dict):
        """
        Update the table with LED information.

        Args:
            led_info_dict: Dictionary mapping LED ID (int) to LEDInfo (enum)
        """
        print(f"StatusTable: update_led_info called with {len(led_info_dict)} LEDs")

        # Store the data
        self.led_data = led_info_dict
        self.sorted_ids = sorted(led_info_dict.keys())

        # Only configure columns if not already done
        if not self.columns_configured:
            self._configure_columns()

        # Update table row count (chunk LEDs across multiple columns)
        led_count = len(led_info_dict)
        rows = math.ceil(led_count / self.pairs_per_row) if led_count else 0
        self.table.setRowCount(rows)

        # Populate table
        for idx, (led_id, led_info) in enumerate(self._sorted_items()):
            row = idx // self.pairs_per_row
            col_base = (idx % self.pairs_per_row) * 2

            status_name = self._status_name(led_info)
            status_color = self.COLORS.get(status_name, self.COLORS["NONE"])

            # LED ID - default gray unless toggled on (dark blue)
            id_item = QTableWidgetItem(str(led_id))
            id_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if led_id in self.manual_on_leds:
                id_item.setBackground(QColor(40, 70, 140))  # Dark blue when toggled
            else:
                id_item.setBackground(QColor(240, 240, 240))  # Default gray
            self.table.setItem(row, col_base, id_item)

            # Status - always shows status color (never changes to dark blue)
            status_text = self._abbreviation(status_name)
            status_item = QTableWidgetItem(status_text)
            status_item.setToolTip(status_name.title())  # Full name on hover
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            status_item.setBackground(status_color)  # Always status color

            self.table.setItem(row, col_base + 1, status_item)

        # Update summary totals
        summary = self.get_summary()
        total_leds = sum(summary.values())
        parts = [f"{self._abbreviation(k)}:{v}" for k, v in summary.items() if v > 0]
        summary_text = " | ".join(parts) if parts else "No data"
        self.summary_label.setText(f"Totals ({total_leds}): {summary_text}")

    def clear_table(self):
        """Clear all data from the table."""
        self.led_data = {}
        self.table.setRowCount(0)

    def get_summary(self):
        """
        Get a summary of LED statuses.

        Returns:
            Dictionary with counts of each status type
        """
        summary = {
            "RECONSTRUCTED": 0,
            "INTERPOLATED": 0,
            "MERGED": 0,
            "DETECTED": 0,
            "UNRECONSTRUCTABLE": 0,
            "NONE": 0,
        }

        for led_info in self.led_data.values():
            status = self._status_name(led_info)
            summary[status if status in summary else "NONE"] += 1

        return summary

    def _sorted_items(self):
        for led_id in self.sorted_ids:
            yield led_id, self.led_data[led_id]

    @pyqtSlot()
    def set_all_on_state(self):
        """Set all LEDs to 'on' state (dark blue ID cells). Visual update only, no signals."""
        print("StatusTable: Setting all LEDs ON (visual state)")
        # Add all LEDs to manual_on_leds set
        for led_id in self.sorted_ids:
            self.manual_on_leds.add(led_id)

        # Update all ID cells to dark blue
        self._update_all_id_cells()

    @pyqtSlot()
    def set_all_off_state(self):
        """Set all LEDs to 'off' state (gray ID cells). Visual update only, no signals."""
        print("StatusTable: Setting all LEDs OFF (visual state)")
        # Clear the manual_on_leds set
        self.manual_on_leds.clear()

        # Update all ID cells to gray
        self._update_all_id_cells()

    def _update_all_id_cells(self):
        """Update all ID cell colors based on manual_on_leds state."""
        for idx, led_id in enumerate(self.sorted_ids):
            row = idx // self.pairs_per_row
            col_base = (idx % self.pairs_per_row) * 2
            id_column = col_base

            id_item = self.table.item(row, id_column)
            if id_item is not None:
                if led_id in self.manual_on_leds:
                    id_item.setBackground(QColor(40, 70, 140))  # Dark blue
                else:
                    id_item.setBackground(QColor(240, 240, 240))  # Gray

    def _on_cell_clicked(self, row: int, column: int):
        """Toggle LED on/off when either ID or status cell is clicked."""
        pair_index = column // 2
        led_index = row * self.pairs_per_row + pair_index
        if led_index < 0 or led_index >= len(self.sorted_ids):
            return

        led_id = self.sorted_ids[led_index]
        turn_on = led_id not in self.manual_on_leds

        if turn_on:
            self.manual_on_leds.add(led_id)
            print(f"StatusTable: LED {led_id} toggled ON (ID cell -> dark blue)")
        else:
            self.manual_on_leds.discard(led_id)
            print(f"StatusTable: LED {led_id} toggled OFF (ID cell -> default gray)")

        # Update only the ID cell color
        id_column = pair_index * 2
        id_item = self.table.item(row, id_column)

        if id_item is not None:
            if turn_on:
                # ID cell goes dark blue when toggled on
                id_item.setBackground(QColor(40, 70, 140))
            else:
                # ID cell returns to default gray
                id_item.setBackground(QColor(240, 240, 240))

        # Status cell keeps its color - no changes needed

        # Emit signal to actually control the LED
        self.led_toggle_requested.emit(led_id, turn_on)
