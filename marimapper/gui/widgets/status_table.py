"""
LED detection status table widget for MariMapper GUI.

Displays the reconstruction status of each LED with color-coded rows.
"""

import math
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView, QLabel
from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QColor


class StatusTable(QWidget):
    """Widget displaying LED reconstruction status in a table."""

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
        self.init_ui()

    def init_ui(self):
        """Initialize the user interface."""
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        # Summary label shows totals by status at a glance
        self.summary_label = QLabel("Totals: (waiting for data)")
        self.summary_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.summary_label)

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
        self.table.cellClicked.connect(self._on_cell_clicked)

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

        # Reconfigure columns in case settings changed
        self._configure_columns()

        # Update table row count (chunk LEDs across multiple columns)
        led_count = len(led_info_dict)
        rows = math.ceil(led_count / self.pairs_per_row) if led_count else 0
        self.table.setRowCount(rows)

        # Populate table
        for idx, (led_id, led_info) in enumerate(self._sorted_items()):
            row = idx // self.pairs_per_row
            col_base = (idx % self.pairs_per_row) * 2

            # LED ID
            id_item = QTableWidgetItem(str(led_id))
            id_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, col_base, id_item)

            # Status (led_info is an LEDInfo enum)
            status_name = self._status_name(led_info)
            status_text = self._abbreviation(status_name)
            status_item = QTableWidgetItem(status_text)
            status_item.setToolTip(status_name.title())  # Full name on hover
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            # Set background color based on status or manual toggle
            if led_id in self.manual_on_leds:
                color = QColor(40, 70, 140)  # dark blue to indicate manual ON
            else:
                color = self.COLORS.get(status_name, self.COLORS["NONE"])
            status_item.setBackground(color)

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
        else:
            self.manual_on_leds.discard(led_id)

        # Update cell color
        status_column = pair_index * 2 + 1
        item = self.table.item(row, status_column)
        if item is not None:
            status_name = self._status_name(self.led_data.get(led_id, "NONE"))
            if turn_on:
                item.setBackground(QColor(40, 70, 140))
            else:
                item.setBackground(self.COLORS.get(status_name, self.COLORS["NONE"]))
