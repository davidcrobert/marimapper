"""
LED detection status table widget for MariMapper GUI.

Displays the reconstruction status of each LED with color-coded rows.
"""

import math
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView, QLabel, QPushButton
from PyQt6.QtCore import Qt, pyqtSlot, pyqtSignal
from PyQt6.QtGui import QColor, QCursor


class StatusTable(QWidget):
    """Widget displaying LED reconstruction status in a table."""

    # Signals
    led_toggle_requested = pyqtSignal(int, bool)  # (led_id, turn_on)
    bulk_led_toggle_requested = pyqtSignal(list)  # [(led_id, turn_on), ...]

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
        self.active_filter = None  # Currently active status filter (None = show all)
        self.filter_buttons = {}  # Map status name to its button widget
        self.init_ui()

    def init_ui(self):
        """Initialize the user interface."""
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        # Summary label shows totals by status at a glance
        self.summary_label = QLabel("Totals: (waiting for data)")
        self.summary_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.summary_label)

        # Top bar: Legend + filter action buttons
        top_bar_layout = QHBoxLayout()
        top_bar_layout.setSpacing(8)
        top_bar_layout.setContentsMargins(4, 2, 4, 2)

        # Compact legend showing status colors and names (clickable for filtering)
        legend_layout = QHBoxLayout()
        legend_layout.setSpacing(3)
        legend_layout.setContentsMargins(0, 0, 0, 0)

        status_info = [
            ("R", "RECONSTRUCTED", "Reconstructed", "3D position found via SfM"),
            ("I", "INTERPOLATED", "Interpolated", "Position calculated between detected LEDs"),
            ("M", "MERGED", "Merged", "Duplicate detections merged"),
            ("D", "DETECTED", "Detected", "Seen in 2D, waiting for 3D reconstruction"),
            ("U", "UNRECONSTRUCTABLE", "Unreconstructable", "Cannot reconstruct 3D position"),
            ("-", "NONE", "None", "Not yet detected"),
        ]

        for abbr, status, display_name, description in status_info:
            # Create clickable button for each status
            status_button = QPushButton()
            status_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

            # Color square as part of button text (using Unicode square)
            color_hex = self.COLORS[status].name()
            status_button.setText(f"  {display_name} ({abbr})")
            status_button.setToolTip(f"{description}\n\nClick to filter table to only {display_name} LEDs.\nClick again to clear filter.")

            # Style button with color square indicator
            status_button.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    border: 2px solid transparent;
                    border-radius: 3px;
                    text-align: left;
                    padding: 2px 4px;
                    font-size: 9px;
                    background-image: qlineargradient(x1:0, y1:0, x2:0.05, y2:0,
                        stop:0 {color_hex}, stop:1 {color_hex});
                    padding-left: 14px;
                }}
                QPushButton:hover {{
                    background-color: rgba(0, 0, 0, 0.05);
                }}
                QPushButton:pressed {{
                    background-color: rgba(0, 0, 0, 0.1);
                }}
            """)

            # Connect click handler
            status_button.clicked.connect(lambda checked, s=status: self._toggle_filter(s))

            # Store button reference for later styling updates
            self.filter_buttons[status] = status_button

            legend_layout.addWidget(status_button)

        legend_layout.addStretch()

        # Add legend to top bar
        top_bar_layout.addLayout(legend_layout, stretch=1)

        # Filter action buttons (initially hidden)
        filter_buttons_layout = QHBoxLayout()
        filter_buttons_layout.setSpacing(4)

        self.filter_all_on_button = QPushButton("Turn All ON")
        self.filter_all_on_button.setToolTip("Turn on all LEDs in the current filter")
        self.filter_all_on_button.setStyleSheet("""
            QPushButton {
                background-color: #28a745;
                color: white;
                border: none;
                border-radius: 3px;
                padding: 4px 8px;
                font-size: 9px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #218838;
            }
            QPushButton:pressed {
                background-color: #1e7e34;
            }
        """)
        self.filter_all_on_button.clicked.connect(self._turn_filtered_on)
        self.filter_all_on_button.setVisible(False)
        filter_buttons_layout.addWidget(self.filter_all_on_button)

        self.filter_all_off_button = QPushButton("Turn All OFF")
        self.filter_all_off_button.setToolTip("Turn off all LEDs in the current filter")
        self.filter_all_off_button.setStyleSheet("""
            QPushButton {
                background-color: #dc3545;
                color: white;
                border: none;
                border-radius: 3px;
                padding: 4px 8px;
                font-size: 9px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #c82333;
            }
            QPushButton:pressed {
                background-color: #bd2130;
            }
        """)
        self.filter_all_off_button.clicked.connect(self._turn_filtered_off)
        self.filter_all_off_button.setVisible(False)
        filter_buttons_layout.addWidget(self.filter_all_off_button)

        top_bar_layout.addLayout(filter_buttons_layout)

        # Wrap in a widget for styling
        legend_widget = QWidget()
        legend_widget.setLayout(top_bar_layout)
        legend_widget.setStyleSheet("QWidget { background-color: #f5f5f5; border: 1px solid #ccc; border-radius: 3px; }")
        legend_widget.setMaximumHeight(26)

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

    def _toggle_filter(self, status: str):
        """Toggle filtering by the selected status."""
        if self.active_filter == status:
            # Clear filter if clicking the same status
            self.active_filter = None
            print(f"StatusTable: Filter cleared")
        else:
            # Set new filter
            self.active_filter = status
            print(f"StatusTable: Filtering by {status}")

        # Update button styles to show active filter
        self._update_filter_button_styles()

        # Show/hide filter action buttons
        self.filter_all_on_button.setVisible(self.active_filter is not None)
        self.filter_all_off_button.setVisible(self.active_filter is not None)

        # Refresh the table display
        self._refresh_table()

    def _update_filter_button_styles(self):
        """Update button styles to highlight the active filter."""
        for status, button in self.filter_buttons.items():
            color_hex = self.COLORS[status].name()

            if status == self.active_filter:
                # Active filter - bold border
                button.setStyleSheet(f"""
                    QPushButton {{
                        background-color: rgba(0, 120, 215, 0.1);
                        border: 2px solid #0078d7;
                        border-radius: 3px;
                        text-align: left;
                        padding: 2px 4px;
                        font-size: 9px;
                        font-weight: bold;
                        background-image: qlineargradient(x1:0, y1:0, x2:0.05, y2:0,
                            stop:0 {color_hex}, stop:1 {color_hex});
                        padding-left: 14px;
                    }}
                    QPushButton:hover {{
                        background-color: rgba(0, 120, 215, 0.15);
                    }}
                """)
            else:
                # Inactive - normal style
                button.setStyleSheet(f"""
                    QPushButton {{
                        background-color: transparent;
                        border: 2px solid transparent;
                        border-radius: 3px;
                        text-align: left;
                        padding: 2px 4px;
                        font-size: 9px;
                        background-image: qlineargradient(x1:0, y1:0, x2:0.05, y2:0,
                            stop:0 {color_hex}, stop:1 {color_hex});
                        padding-left: 14px;
                    }}
                    QPushButton:hover {{
                        background-color: rgba(0, 0, 0, 0.05);
                    }}
                    QPushButton:pressed {{
                        background-color: rgba(0, 0, 0, 0.1);
                    }}
                """)

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

        # Refresh the table with current filter
        self._refresh_table()

    def _refresh_table(self):
        """Refresh the table display with current data and filter."""
        # Get filtered LEDs
        filtered_items = list(self._filtered_items())
        led_count = len(filtered_items)

        # Update table row count (chunk LEDs across multiple columns)
        rows = math.ceil(led_count / self.pairs_per_row) if led_count else 0
        self.table.setRowCount(rows)

        # Clear all existing cells to prevent old data from showing
        self.table.clearContents()

        # Populate table
        for idx, (led_id, led_info) in enumerate(filtered_items):
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

        # Show filter status in summary
        if self.active_filter is not None:
            filter_abbr = self._abbreviation(self.active_filter)
            self.summary_label.setText(f"Filtered: {led_count} {filter_abbr} LEDs | Total ({total_leds}): {summary_text}")
        else:
            self.summary_label.setText(f"Totals ({total_leds}): {summary_text}")

    def clear_table(self):
        """Clear all data from the table."""
        self.led_data = {}
        self.active_filter = None
        self._update_filter_button_styles()
        self.filter_all_on_button.setVisible(False)
        self.filter_all_off_button.setVisible(False)
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
        """Iterate over all LED items in sorted order."""
        for led_id in self.sorted_ids:
            yield led_id, self.led_data[led_id]

    def _filtered_items(self):
        """Iterate over LED items matching the current filter."""
        for led_id in self.sorted_ids:
            led_info = self.led_data[led_id]
            status_name = self._status_name(led_info)

            # If no filter is active, show all
            if self.active_filter is None:
                yield led_id, led_info
            # If filter is active, only show matching status
            elif status_name == self.active_filter:
                yield led_id, led_info

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

        # Get the LED ID from filtered items (not sorted_ids, since table shows filtered view)
        filtered_list = list(self._filtered_items())
        if led_index < 0 or led_index >= len(filtered_list):
            return

        led_id = filtered_list[led_index][0]  # Get LED ID from (led_id, led_info) tuple
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

    def _turn_filtered_on(self):
        """Turn on all LEDs in the current filter."""
        if self.active_filter is None:
            return

        filtered_ids = [led_id for led_id, _ in self._filtered_items()]
        print(f"StatusTable: Turning ON {len(filtered_ids)} filtered LEDs ({self.active_filter})")

        # Build list of LEDs that need to change state
        changes = []
        for led_id in filtered_ids:
            if led_id not in self.manual_on_leds:
                self.manual_on_leds.add(led_id)
                changes.append((led_id, True))

        # Emit bulk signal to control all LEDs at once
        if changes:
            self.bulk_led_toggle_requested.emit(changes)

        # Refresh table to show updated visual state
        self._refresh_table()

    def _turn_filtered_off(self):
        """Turn off all LEDs in the current filter."""
        if self.active_filter is None:
            return

        filtered_ids = [led_id for led_id, _ in self._filtered_items()]
        print(f"StatusTable: Turning OFF {len(filtered_ids)} filtered LEDs ({self.active_filter})")

        # Build list of LEDs that need to change state
        changes = []
        for led_id in filtered_ids:
            if led_id in self.manual_on_leds:
                self.manual_on_leds.discard(led_id)
                changes.append((led_id, False))

        # Emit bulk signal to control all LEDs at once
        if changes:
            self.bulk_led_toggle_requested.emit(changes)

        # Refresh table to show updated visual state
        self._refresh_table()
