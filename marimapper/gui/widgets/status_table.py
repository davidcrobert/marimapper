"""
LED detection status table widget for MariMapper GUI.

Displays the reconstruction status of each LED with color-coded rows.
"""

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
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["LED ID", "Status"])

        # Configure table appearance
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(18)  # Smaller rows to fit more

        # Set column stretch
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

        # Set column widths
        self.table.setColumnWidth(0, 60)  # LED ID column slimmer

        layout.addWidget(self.table)
        layout.setStretch(1, 1)  # Let table grab vertical space
        self.setLayout(layout)

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

        # Update table row count
        self.table.setRowCount(len(led_info_dict))

        # Populate table
        for row, (led_id, led_info) in enumerate(sorted(led_info_dict.items())):
            # LED ID
            id_item = QTableWidgetItem(str(led_id))
            id_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 0, id_item)

            # Status (led_info is an LEDInfo enum)
            status_name = self._status_name(led_info)
            status_text = self._abbreviation(status_name)
            status_item = QTableWidgetItem(status_text)
            status_item.setToolTip(status_name.title())  # Full name on hover
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            # Set background color based on status
            color = self.COLORS.get(status_name, self.COLORS["NONE"])
            status_item.setBackground(color)

            self.table.setItem(row, 1, status_item)

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
