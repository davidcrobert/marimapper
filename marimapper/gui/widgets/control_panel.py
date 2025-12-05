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
    QComboBox,
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
    all_on_requested = pyqtSignal()  # Turn all LEDs on
    # Mask control signals
    paint_mode_toggled = pyqtSignal(bool)  # Enable/disable painting
    brush_size_changed = pyqtSignal(int)  # Brush size value
    mask_visibility_toggled = pyqtSignal(bool)  # Show/hide mask
    mask_clear_requested = pyqtSignal()  # Clear mask
    mask_save_requested = pyqtSignal()  # Save mask to file
    mask_load_requested = pyqtSignal()  # Load mask from file
    camera_selected = pyqtSignal(int)  # For multi-camera mask selection

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

        # Horizontal layout for View Info and Scan Controls (side by side)
        info_scan_layout = QHBoxLayout()

        # View Info Group (horizontal layout)
        view_info_group = QGroupBox("View Information")
        view_info_layout = QVBoxLayout()

        # First row: Views captured
        views_layout = QHBoxLayout()
        views_layout.addWidget(QLabel("Views:"))
        self.view_count_label = QLabel(str(self.view_count))
        views_layout.addWidget(self.view_count_label)
        views_layout.addStretch()
        view_info_layout.addLayout(views_layout)

        # Second row: Total LEDs
        leds_layout = QHBoxLayout()
        leds_layout.addWidget(QLabel("Total LEDs:"))
        self.led_count_label = QLabel(str(self.led_count))
        leds_layout.addWidget(self.led_count_label)
        leds_layout.addStretch()
        view_info_layout.addLayout(leds_layout)

        view_info_group.setLayout(view_info_layout)
        info_scan_layout.addWidget(view_info_group)

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

        # Mask Controls
        mask_controls_group = QGroupBox("Mask Controls")
        mask_controls_layout = QVBoxLayout()

        # Camera selector (multi-camera only - will be hidden by default)
        self.camera_selector_layout = QHBoxLayout()
        self.camera_selector_label = QLabel("Camera:")
        self.camera_selector_layout.addWidget(self.camera_selector_label)

        self.camera_selector = QComboBox()
        self.camera_selector.currentIndexChanged.connect(self.on_camera_selected)
        self.camera_selector_layout.addWidget(self.camera_selector)

        # Hide by default (only show if multi-camera)
        self.camera_selector_label.setVisible(False)
        self.camera_selector.setVisible(False)

        mask_controls_layout.addLayout(self.camera_selector_layout)

        # Toggle painting mode button
        self.paint_mode_button = QPushButton("Enable Paint Mode")
        self.paint_mode_button.setCheckable(True)
        self.paint_mode_button.setToolTip(
            "Enable painting to mask areas (click-drag on video)"
        )
        self.paint_mode_button.clicked.connect(self.on_paint_mode_toggled)
        mask_controls_layout.addWidget(self.paint_mode_button)

        # Brush size slider
        brush_size_label = QLabel("Brush Size:")
        mask_controls_layout.addWidget(brush_size_label)

        brush_size_layout = QHBoxLayout()
        self.brush_size_slider = QSlider(Qt.Orientation.Horizontal)
        self.brush_size_slider.setMinimum(1)
        self.brush_size_slider.setMaximum(100)
        self.brush_size_slider.setValue(20)
        self.brush_size_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.brush_size_slider.setTickInterval(10)
        self.brush_size_slider.valueChanged.connect(self.on_brush_size_changed)
        brush_size_layout.addWidget(self.brush_size_slider)

        self.brush_size_value_label = QLabel("20")
        self.brush_size_value_label.setMinimumWidth(35)
        self.brush_size_value_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        brush_size_layout.addWidget(self.brush_size_value_label)

        mask_controls_layout.addLayout(brush_size_layout)

        # Mask action buttons
        mask_button_layout = QHBoxLayout()

        self.toggle_mask_button = QPushButton("Hide Mask")
        self.toggle_mask_button.setToolTip("Show/hide mask overlay")
        self.toggle_mask_button.clicked.connect(self.on_toggle_mask_visibility)
        mask_button_layout.addWidget(self.toggle_mask_button)

        self.clear_mask_button = QPushButton("Clear Mask")
        self.clear_mask_button.setToolTip("Remove all painted mask areas")
        self.clear_mask_button.clicked.connect(self.on_clear_mask)
        mask_button_layout.addWidget(self.clear_mask_button)

        mask_controls_layout.addLayout(mask_button_layout)

        # Save/Load mask buttons
        mask_file_layout = QHBoxLayout()

        self.save_mask_button = QPushButton("Save Mask")
        self.save_mask_button.setToolTip("Save mask to file for later use")
        self.save_mask_button.clicked.connect(self.on_save_mask)
        mask_file_layout.addWidget(self.save_mask_button)

        self.load_mask_button = QPushButton("Load Mask")
        self.load_mask_button.setToolTip("Load mask from file")
        self.load_mask_button.clicked.connect(self.on_load_mask)
        mask_file_layout.addWidget(self.load_mask_button)

        mask_controls_layout.addLayout(mask_file_layout)

        mask_controls_group.setLayout(mask_controls_layout)
        layout.addWidget(mask_controls_group)

        # Scan Controls (placed next to View Info, buttons side-by-side)
        scan_controls_group = QGroupBox("Scan Controls")
        scan_controls_layout = QVBoxLayout()

        # Buttons in horizontal layout
        buttons_layout = QHBoxLayout()
        self.start_button = QPushButton("Start")
        self.start_button.clicked.connect(self.on_start_scan)
        self.start_button.setEnabled(True)
        buttons_layout.addWidget(self.start_button)

        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self.on_stop_scan)
        self.stop_button.setEnabled(False)
        buttons_layout.addWidget(self.stop_button)

        scan_controls_layout.addLayout(buttons_layout)

        # Status label below buttons
        self.status_label = QLabel("Status: Ready")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scan_controls_layout.addWidget(self.status_label)

        scan_controls_group.setLayout(scan_controls_layout)
        info_scan_layout.addWidget(scan_controls_group)

        # Add the horizontal layout (View Info + Scan Controls) to main layout
        layout.addLayout(info_scan_layout)

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
        self.led_count_label.setText(str(count))
        self.led_to_spinbox.setValue(count)
        self.led_to_spinbox.setMaximum(count)

    def scan_completed(self):
        """Called when a scan completes successfully."""
        self.view_count += 1
        self.view_count_label.setText(str(self.view_count))
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
        self.view_count_label.setText(str(self.view_count))

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

    def on_paint_mode_toggled(self, checked: bool):
        """Handle paint mode button toggle."""
        if checked:
            self.paint_mode_button.setText("Disable Paint Mode")
            self.paint_mode_button.setStyleSheet("background-color: #ff6b6b;")
        else:
            self.paint_mode_button.setText("Enable Paint Mode")
            self.paint_mode_button.setStyleSheet("")
        self.paint_mode_toggled.emit(checked)

    def on_brush_size_changed(self, value: int):
        """Handle brush size slider change."""
        self.brush_size_value_label.setText(str(value))
        self.brush_size_changed.emit(value)

    def on_toggle_mask_visibility(self):
        """Handle toggle mask visibility button."""
        # Toggle button text
        if self.toggle_mask_button.text() == "Hide Mask":
            self.toggle_mask_button.setText("Show Mask")
            self.mask_visibility_toggled.emit(False)
        else:
            self.toggle_mask_button.setText("Hide Mask")
            self.mask_visibility_toggled.emit(True)

    def on_clear_mask(self):
        """Handle clear mask button click."""
        self.mask_clear_requested.emit()

    def on_save_mask(self):
        """Handle save mask button click."""
        self.mask_save_requested.emit()

    def on_load_mask(self):
        """Handle load mask button click."""
        self.mask_load_requested.emit()

    def on_camera_selected(self, index: int):
        """Handle camera selection change."""
        self.camera_selected.emit(index)

    def set_camera_count(self, count: int):
        """Populate camera selector dropdown if count > 1."""
        if count > 1:
            # Show camera selector
            self.camera_selector_label.setVisible(True)
            self.camera_selector.setVisible(True)

            # Populate dropdown
            self.camera_selector.clear()
            for i in range(count):
                self.camera_selector.addItem(f"Camera {i}")
        else:
            # Hide for single camera
            self.camera_selector_label.setVisible(False)
            self.camera_selector.setVisible(False)
