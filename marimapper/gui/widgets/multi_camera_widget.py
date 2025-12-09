"""
MultiCameraWidget - Grid widget for displaying multiple camera feeds.

This widget manages a grid of DetectorWidget instances, one per camera,
with support for independent mask painting, fullscreen toggle, and
camera selection.
"""

from PyQt6.QtWidgets import QWidget, QGridLayout, QLabel
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QPalette, QColor
import numpy as np
from marimapper.gui.widgets.detector_widget import DetectorWidget


class MultiCameraWidget(QWidget):
    """Grid widget for displaying multiple camera feeds with independent controls."""

    # Signals
    camera_selected = pyqtSignal(int)  # Emitted when user clicks a camera
    mask_updated = pyqtSignal(int, object)  # camera_index, mask_numpy

    def __init__(self, camera_count: int, parent=None):
        """
        Initialize multi-camera grid widget.

        Args:
            camera_count: Number of cameras to display (1-9)
            parent: Parent widget
        """
        super().__init__(parent)

        if camera_count < 1 or camera_count > 9:
            raise ValueError(f"MultiCameraWidget supports 1-9 cameras, got {camera_count}")

        self.camera_count = camera_count
        self.detector_widgets = []  # List of DetectorWidget instances
        self.camera_labels = []  # List of QLabel overlays
        self.active_camera = 0
        self.fullscreen_camera = None  # None or camera_index

        # Calculate grid dimensions
        if camera_count <= 4:
            self.grid_rows, self.grid_cols = 2, 2
        elif camera_count <= 9:
            self.grid_rows, self.grid_cols = 3, 3
        else:
            raise ValueError(f"MultiCameraWidget supports max 9 cameras, got {camera_count}")

        self._setup_ui()

    def _setup_ui(self):
        """Create grid layout with camera widgets."""
        layout = QGridLayout()
        layout.setSpacing(2)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

        # Create DetectorWidget for each camera
        for camera_id in range(self.camera_count):
            widget = self._create_camera_widget(camera_id)
            self.detector_widgets.append(widget)

            # Place in grid
            row = camera_id // self.grid_cols
            col = camera_id % self.grid_cols
            layout.addWidget(widget, row, col)

            # Connect signals
            widget.maximize_toggled.connect(
                lambda checked, idx=camera_id: self.toggle_fullscreen(idx)
            )
            widget.mask_updated.connect(
                lambda mask, idx=camera_id: self.mask_updated.emit(idx, mask)
            )

        # Set initial active camera highlight
        self.set_active_camera(0)

    def _create_camera_widget(self, camera_id: int):
        """
        Create DetectorWidget with camera label overlay.

        Args:
            camera_id: Camera index (0-based)

        Returns:
            DetectorWidget instance
        """
        widget = DetectorWidget()

        # Add camera label overlay
        label = QLabel(f"Camera {camera_id + 1}", widget)
        label.setStyleSheet("""
            QLabel {
                background-color: rgba(0, 0, 0, 150);
                color: white;
                padding: 5px 10px;
                border-radius: 3px;
                font-size: 12px;
                font-weight: bold;
            }
        """)
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        label.move(10, 10)
        label.raise_()
        label.show()
        self.camera_labels.append(label)

        # Override mousePressEvent for auto-switch behavior
        original_mouse_press = widget.mousePressEvent

        def camera_click_handler(event):
            # Auto-select this camera when clicked
            if not widget.painting_mode:
                self.set_active_camera(camera_id)
                self.camera_selected.emit(camera_id)
            # Call original handler
            original_mouse_press(event)

        widget.mousePressEvent = camera_click_handler

        return widget

    def set_active_camera(self, camera_index: int):
        """
        Highlight the active camera for mask editing.

        Args:
            camera_index: Index of camera to make active (0-based)
        """
        if camera_index < 0 or camera_index >= self.camera_count:
            return

        self.active_camera = camera_index

        # Update visual indicators (highlight active camera)
        for i, widget in enumerate(self.detector_widgets):
            if i == camera_index:
                widget.setStyleSheet("border: 3px solid #00FF00;")
            else:
                widget.setStyleSheet("border: 1px solid #333333;")

    def update_frame(self, camera_index: int, frame: np.ndarray):
        """
        Route frame to specific camera widget.

        Args:
            camera_index: Index of camera (0-based)
            frame: Video frame (numpy array)
        """
        if camera_index < 0 or camera_index >= len(self.detector_widgets):
            return
        self.detector_widgets[camera_index].update_frame(frame)

    def toggle_fullscreen(self, camera_index: int):
        """
        Toggle fullscreen for specific camera.

        Args:
            camera_index: Index of camera to fullscreen (0-based)
        """
        if self.fullscreen_camera == camera_index:
            # Restore grid
            self.fullscreen_camera = None
            self._show_grid()
        else:
            # Show only this camera
            self.fullscreen_camera = camera_index
            self._show_fullscreen(camera_index)

    def _show_grid(self):
        """Restore grid layout with all cameras visible."""
        layout = self.layout()

        # Clear layout
        for i in reversed(range(layout.count())):
            item = layout.itemAt(i)
            if item and item.widget():
                layout.removeWidget(item.widget())

        # Re-add all widgets in grid positions
        for i, widget in enumerate(self.detector_widgets):
            row = i // self.grid_cols
            col = i % self.grid_cols
            layout.addWidget(widget, row, col)
            widget.show()

    def _show_fullscreen(self, camera_index: int):
        """
        Show only one camera in fullscreen.

        Args:
            camera_index: Index of camera to show fullscreen (0-based)
        """
        layout = self.layout()

        # Hide all widgets
        for i, widget in enumerate(self.detector_widgets):
            if i != camera_index:
                widget.hide()
                layout.removeWidget(widget)

        # Expand selected camera to full grid
        layout.removeWidget(self.detector_widgets[camera_index])
        layout.addWidget(
            self.detector_widgets[camera_index],
            0, 0,  # Start position
            self.grid_rows, self.grid_cols  # Span entire grid
        )
        self.detector_widgets[camera_index].show()

    def set_painting_mode(self, enabled: bool):
        """
        Set painting mode for active camera only.

        Args:
            enabled: True to enable painting mode, False to disable
        """
        if self.active_camera < len(self.detector_widgets):
            self.detector_widgets[self.active_camera].set_painting_mode(enabled)

    def set_brush_size(self, size: int):
        """
        Set brush size for active camera only.

        Args:
            size: Brush size in pixels
        """
        if self.active_camera < len(self.detector_widgets):
            self.detector_widgets[self.active_camera].set_brush_size(size)

    def set_mask_visibility(self, visible: bool):
        """
        Set mask visibility for active camera only.

        Args:
            visible: True to show mask, False to hide
        """
        if self.active_camera < len(self.detector_widgets):
            self.detector_widgets[self.active_camera].set_mask_visibility(visible)

    def set_mask_from_numpy(self, camera_index: int, mask):
        """
        Load mask for specific camera.

        Args:
            camera_index: Index of camera (0-based)
            mask: Mask as numpy array (H, W) uint8, or None to clear
        """
        if camera_index < len(self.detector_widgets):
            self.detector_widgets[camera_index].set_mask_from_numpy(mask)

    def clear_mask(self, camera_index: int):
        """
        Clear mask for specific camera.

        Args:
            camera_index: Index of camera (0-based)
        """
        if camera_index < len(self.detector_widgets):
            self.detector_widgets[camera_index].set_mask_from_numpy(None)
