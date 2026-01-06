"""
Universe management widget for MariMapper GUI.

Allows users to configure multiple universes with individual LED ranges.
"""

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QMessageBox,
    QLabel,
)
from PyQt6.QtCore import pyqtSignal, Qt
from typing import List, Dict


class UniversesWidget(QWidget):
    """Widget for managing universes and their LED ranges."""

    # Signals
    universes_changed = pyqtSignal(list)  # Emits list of universe configs when changed

    def __init__(self, parent=None):
        super().__init__(parent)
        self.universes: List[Dict[str, int]] = []
        self.init_ui()

    def init_ui(self):
        """Initialize the user interface."""
        layout = QVBoxLayout()

        # Header with instructions
        header_label = QLabel(
            "Configure universes with individual LED ranges. "
            "During scanning, LEDs will be stepped through universe by universe."
        )
        header_label.setWordWrap(True)
        header_label.setStyleSheet("padding: 10px; background-color: #f0f0f0; border-radius: 5px;")
        layout.addWidget(header_label)

        # Table for universes
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Universe", "LED From", "LED To"])

        # Configure table
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)

        # Connect cell change signal
        self.table.cellChanged.connect(self.on_cell_changed)

        layout.addWidget(self.table)

        # Buttons
        button_layout = QHBoxLayout()

        self.add_button = QPushButton("Add Universe")
        self.add_button.clicked.connect(self.add_universe)
        button_layout.addWidget(self.add_button)

        self.remove_button = QPushButton("Remove Selected")
        self.remove_button.clicked.connect(self.remove_universe)
        self.remove_button.setEnabled(False)
        button_layout.addWidget(self.remove_button)

        button_layout.addStretch()

        # Summary label
        self.summary_label = QLabel("Total universes: 0 | Total LEDs: 0")
        button_layout.addWidget(self.summary_label)

        layout.addLayout(button_layout)

        # Connect selection change
        self.table.itemSelectionChanged.connect(self.on_selection_changed)

        self.setLayout(layout)

    def add_universe(self):
        """Add a new universe to the table."""
        # Determine next universe number
        if self.universes:
            next_universe = max(u["universe"] for u in self.universes) + 1
            last_led_to = self.universes[-1]["led_to"]
            next_from = last_led_to
            next_to = next_from + 170  # Default 170 LEDs per universe
        else:
            next_universe = 0
            next_from = 0
            next_to = 170

        # Add to internal list
        universe_config = {
            "universe": next_universe,
            "led_from": next_from,
            "led_to": next_to
        }
        self.universes.append(universe_config)

        # Add to table
        self._add_table_row(universe_config)

        # Update summary and emit signal
        self.update_summary()
        self.universes_changed.emit(self.universes)

    def remove_universe(self):
        """Remove the selected universe."""
        selected_row = self.table.currentRow()
        if selected_row < 0:
            return

        # Confirm deletion
        universe_num = self.universes[selected_row]["universe"]
        reply = QMessageBox.question(
            self,
            "Remove Universe",
            f"Are you sure you want to remove Universe {universe_num}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            # Remove from internal list
            del self.universes[selected_row]

            # Remove from table
            self.table.removeRow(selected_row)

            # Update summary and emit signal
            self.update_summary()
            self.universes_changed.emit(self.universes)

    def _add_table_row(self, universe_config: Dict[str, int]):
        """Add a row to the table for a universe configuration."""
        row = self.table.rowCount()
        self.table.insertRow(row)

        # Block signals while adding items
        self.table.blockSignals(True)

        # Universe column (editable)
        universe_item = QTableWidgetItem(str(universe_config["universe"]))
        universe_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, 0, universe_item)

        # LED From column (editable)
        from_item = QTableWidgetItem(str(universe_config["led_from"]))
        from_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, 1, from_item)

        # LED To column (editable)
        to_item = QTableWidgetItem(str(universe_config["led_to"]))
        to_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, 2, to_item)

        self.table.blockSignals(False)

    def on_cell_changed(self, row: int, column: int):
        """Handle cell changes in the table."""
        if row >= len(self.universes):
            return

        try:
            item = self.table.item(row, column)
            value = int(item.text())

            if value < 0:
                raise ValueError("Value cannot be negative")

            # Update internal data
            if column == 0:  # Universe
                self.universes[row]["universe"] = value
            elif column == 1:  # LED From
                self.universes[row]["led_from"] = value
            elif column == 2:  # LED To
                self.universes[row]["led_to"] = value

            # Validate LED range
            if self.universes[row]["led_from"] >= self.universes[row]["led_to"]:
                QMessageBox.warning(
                    self,
                    "Invalid Range",
                    "LED From must be less than LED To"
                )
                # Revert to previous value
                self.reload_table()
                return

            # Update summary and emit signal
            self.update_summary()
            self.universes_changed.emit(self.universes)

        except ValueError:
            QMessageBox.warning(
                self,
                "Invalid Value",
                "Please enter a valid integer value"
            )
            # Revert to previous value
            self.reload_table()

    def reload_table(self):
        """Reload the table from internal data."""
        self.table.blockSignals(True)
        self.table.setRowCount(0)

        for universe_config in self.universes:
            self._add_table_row(universe_config)

        self.table.blockSignals(False)

    def on_selection_changed(self):
        """Handle selection change in the table."""
        has_selection = len(self.table.selectedItems()) > 0
        self.remove_button.setEnabled(has_selection)

    def update_summary(self):
        """Update the summary label."""
        total_universes = len(self.universes)
        total_leds = sum(u["led_to"] - u["led_from"] for u in self.universes)
        self.summary_label.setText(f"Total universes: {total_universes} | Total LEDs: {total_leds}")

    def set_universes(self, universes: List[Dict[str, int]]):
        """Set the universes configuration (from project load)."""
        self.universes = universes.copy() if universes else []
        self.reload_table()
        self.update_summary()

    def get_universes(self) -> List[Dict[str, int]]:
        """Get the current universes configuration."""
        return self.universes.copy()

    def clear_universes(self):
        """Clear all universes."""
        self.universes.clear()
        self.table.setRowCount(0)
        self.update_summary()
        self.universes_changed.emit(self.universes)
