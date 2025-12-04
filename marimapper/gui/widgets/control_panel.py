"""
Control panel widget for MariMapper GUI.

Provides controls for starting/stopping scans and configuring scan parameters.
"""

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QPushButton,
    QLabel,
    QSpinBox,
)
from PyQt6.QtCore import pyqtSignal


class ControlPanel(QWidget):
    """Control panel for scanner operations."""

    # Signals
    start_scan_requested = pyqtSignal(int, int)  # led_from, led_to
    stop_scan_requested = pyqtSignal()

    def __init__(self, led_count: int = 0, parent=None):
        super().__init__(parent)
        self.led_count = led_count
        self.view_count = 0
        self.is_scanning = False
        self.init_ui()

    def init_ui(self):
        """Initialize the user interface."""
        layout = QVBoxLayout()

        # LED Range Group
        led_range_group = QGroupBox("LED Range")
        led_range_layout = QVBoxLayout()

        # LED From
        led_from_layout = QHBoxLayout()
        led_from_layout.addWidget(QLabel("From:"))
        self.led_from_spinbox = QSpinBox()
        self.led_from_spinbox.setMinimum(0)
        self.led_from_spinbox.setMaximum(9999)
        self.led_from_spinbox.setValue(0)
        led_from_layout.addWidget(self.led_from_spinbox)
        led_range_layout.addLayout(led_from_layout)

        # LED To
        led_to_layout = QHBoxLayout()
        led_to_layout.addWidget(QLabel("To:"))
        self.led_to_spinbox = QSpinBox()
        self.led_to_spinbox.setMinimum(0)
        self.led_to_spinbox.setMaximum(9999)
        self.led_to_spinbox.setValue(self.led_count if self.led_count > 0 else 100)
        led_to_layout.addWidget(self.led_to_spinbox)
        led_range_layout.addLayout(led_to_layout)

        led_range_group.setLayout(led_range_layout)
        layout.addWidget(led_range_group)

        # View Info Group
        view_info_group = QGroupBox("View Information")
        view_info_layout = QVBoxLayout()

        self.view_count_label = QLabel(f"Views captured: {self.view_count}")
        view_info_layout.addWidget(self.view_count_label)

        self.led_count_label = QLabel(f"Total LEDs: {self.led_count}")
        view_info_layout.addWidget(self.led_count_label)

        view_info_group.setLayout(view_info_layout)
        layout.addWidget(view_info_group)

        # Scan Controls
        scan_controls_group = QGroupBox("Scan Controls")
        scan_controls_layout = QVBoxLayout()

        self.start_button = QPushButton("Start Scan")
        self.start_button.clicked.connect(self.on_start_scan)
        self.start_button.setEnabled(True)
        scan_controls_layout.addWidget(self.start_button)

        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self.on_stop_scan)
        self.stop_button.setEnabled(False)
        scan_controls_layout.addWidget(self.stop_button)

        self.status_label = QLabel("Status: Ready")
        scan_controls_layout.addWidget(self.status_label)

        scan_controls_group.setLayout(scan_controls_layout)
        layout.addWidget(scan_controls_group)

        # Add stretch to push everything to the top
        layout.addStretch()

        self.setLayout(layout)

    def on_start_scan(self):
        """Handle start scan button click."""
        led_from = self.led_from_spinbox.value()
        led_to = self.led_to_spinbox.value()

        if led_from >= led_to:
            self.status_label.setText("Error: 'From' must be less than 'To'")
            return

        self.is_scanning = True
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.status_label.setText(f"Status: Scanning LEDs {led_from}-{led_to}...")

        self.start_scan_requested.emit(led_from, led_to)

    def on_stop_scan(self):
        """Handle stop scan button click."""
        self.is_scanning = False
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.status_label.setText("Status: Stopping...")

        self.stop_scan_requested.emit()

    def set_led_count(self, count: int):
        """Update the LED count."""
        self.led_count = count
        self.led_count_label.setText(f"Total LEDs: {count}")
        self.led_to_spinbox.setValue(count)
        self.led_to_spinbox.setMaximum(count)

    def scan_completed(self):
        """Called when a scan completes successfully."""
        self.view_count += 1
        self.view_count_label.setText(f"Views captured: {self.view_count}")
        self.is_scanning = False
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.status_label.setText("Status: Scan completed")

    def scan_failed(self, error_msg: str):
        """Called when a scan fails."""
        self.is_scanning = False
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.status_label.setText(f"Status: Failed - {error_msg}")

    def reset_view_count(self):
        """Reset the view counter."""
        self.view_count = 0
        self.view_count_label.setText(f"Views captured: {self.view_count}")
