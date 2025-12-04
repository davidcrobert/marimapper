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
    QSlider,
)
from PyQt6.QtCore import pyqtSignal, Qt


class ControlPanel(QWidget):
    """Control panel for scanner operations."""

    # Signals
    start_scan_requested = pyqtSignal(int, int)  # led_from, led_to
    stop_scan_requested = pyqtSignal()
    exposure_dark_requested = pyqtSignal()  # Set camera to dark mode
    exposure_bright_requested = pyqtSignal()  # Set camera to bright mode
    threshold_changed = pyqtSignal(int)  # New threshold value (0-255)
    all_off_requested = pyqtSignal()  # Turn all LEDs off
    all_on_requested = pyqtSignal()   # Turn all LEDs on

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

        # Camera Controls
        camera_controls_group = QGroupBox("Camera Controls")
        camera_controls_layout = QVBoxLayout()

        # Exposure toggle buttons
        exposure_layout = QHBoxLayout()

        self.dark_button = QPushButton("Dark Mode")
        self.dark_button.setToolTip("Close iris / Lower exposure for LED detection")
        self.dark_button.clicked.connect(self.on_exposure_dark)
        exposure_layout.addWidget(self.dark_button)

        self.bright_button = QPushButton("Bright Mode")
        self.bright_button.setToolTip("Open iris / Normal exposure for preview")
        self.bright_button.clicked.connect(self.on_exposure_bright)
        exposure_layout.addWidget(self.bright_button)

        camera_controls_layout.addLayout(exposure_layout)

        # Global LED controls
        led_power_layout = QHBoxLayout()
        self.all_off_button = QPushButton("All Off")
        self.all_off_button.setToolTip("Turn off all LEDs/pixels")
        self.all_off_button.clicked.connect(self.on_all_off)
        led_power_layout.addWidget(self.all_off_button)

        self.all_on_button = QPushButton("All On")
        self.all_on_button.setToolTip("Turn on all LEDs/pixels")
        self.all_on_button.clicked.connect(self.on_all_on)
        led_power_layout.addWidget(self.all_on_button)

        camera_controls_layout.addLayout(led_power_layout)

        self.exposure_status_label = QLabel("Mode: Normal")
        camera_controls_layout.addWidget(self.exposure_status_label)

        # Threshold slider
        threshold_label = QLabel("Detection Threshold:")
        camera_controls_layout.addWidget(threshold_label)

        threshold_layout = QHBoxLayout()

        self.threshold_slider = QSlider(Qt.Orientation.Horizontal)
        self.threshold_slider.setMinimum(0)
        self.threshold_slider.setMaximum(255)
        self.threshold_slider.setValue(128)  # Default threshold
        self.threshold_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.threshold_slider.setTickInterval(25)
        self.threshold_slider.valueChanged.connect(self.on_threshold_changed)
        threshold_layout.addWidget(self.threshold_slider)

        self.threshold_value_label = QLabel("128")
        self.threshold_value_label.setMinimumWidth(35)
        self.threshold_value_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        threshold_layout.addWidget(self.threshold_value_label)

        camera_controls_layout.addLayout(threshold_layout)

        camera_controls_group.setLayout(camera_controls_layout)
        layout.addWidget(camera_controls_group)

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

    def on_exposure_dark(self):
        """Handle dark mode button click."""
        self.exposure_status_label.setText("Mode: Dark (LED Detection)")
        self.exposure_dark_requested.emit()

    def on_exposure_bright(self):
        """Handle bright mode button click."""
        self.exposure_status_label.setText("Mode: Bright (Normal)")
        self.exposure_bright_requested.emit()

    def on_threshold_changed(self, value: int):
        """Handle threshold slider change."""
        self.threshold_value_label.setText(str(value))
        self.threshold_changed.emit(value)

    def on_all_off(self):
        """Handle All Off button click."""
        self.all_off_requested.emit()

    def on_all_on(self):
        """Handle All On button click."""
        self.all_on_requested.emit()
