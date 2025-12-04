"""
LED detection status table widget for MariMapper GUI.

Displays the reconstruction status of each LED with color-coded rows.
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView
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

    def __init__(self, parent=None):
        super().__init__(parent)
        self.led_data = {}  # LED ID -> LEDInfo (enum)
        self.init_ui()

    def init_ui(self):
        """Initialize the user interface."""
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        # Create table
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["LED ID", "Status"])

        # Configure table appearance
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)

        # Set column stretch
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

        # Set column widths
        self.table.setColumnWidth(0, 80)  # LED ID

        layout.addWidget(self.table)
        self.setLayout(layout)

    @pyqtSlot(dict)
    def update_led_info(self, led_info_dict: dict):
        """
        Update the table with LED information.

        Args:
            led_info_dict: Dictionary mapping LED ID (int) to LEDInfo (enum)
        """
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
            status_text = led_info.name
            status_item = QTableWidgetItem(status_text)
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            # Set background color based on status
            color = self.COLORS.get(status_text, self.COLORS["NONE"])
            status_item.setBackground(color)

            self.table.setItem(row, 1, status_item)

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
            status = led_info.type.name if hasattr(led_info, 'type') else "NONE"
            if status in summary:
                summary[status] += 1

        return summary
