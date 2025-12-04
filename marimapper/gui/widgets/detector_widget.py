"""
Detector video display widget for MariMapper GUI.

Displays the live camera feed from the detector process with LED detections.
"""

import numpy as np
from PyQt6.QtWidgets import QWidget, QLabel, QVBoxLayout, QPushButton
from PyQt6.QtCore import Qt, pyqtSlot, pyqtSignal
from PyQt6.QtGui import QPixmap

from marimapper.gui.utils.image_utils import numpy_to_qpixmap, scale_qpixmap


class DetectorWidget(QWidget):
    """Widget for displaying the detector camera feed."""

    # Signal emitted when maximize/minimize is toggled
    maximize_toggled = pyqtSignal(bool)  # True = maximize, False = restore

    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_maximized = False
        self.init_ui()

    def init_ui(self):
        """Initialize the user interface."""
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        # Video display label
        self.video_label = QLabel()
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setStyleSheet("QLabel { background-color: black; }")
        self.video_label.setMinimumSize(640, 480)
        self.video_label.setText("Waiting for camera feed...")
        self.video_label.setStyleSheet(
            "QLabel { background-color: black; color: white; font-size: 14px; }"
        )
        # Enable mouse tracking for double-click
        self.video_label.setMouseTracking(True)
        self.video_label.mouseDoubleClickEvent = self._on_double_click

        # Maximize/Minimize button
        self.maximize_button = QPushButton("⛶")  # Maximize icon
        self.maximize_button.setToolTip("Maximize video (or double-click video)")
        self.maximize_button.setFixedSize(30, 30)
        self.maximize_button.setStyleSheet("""
            QPushButton {
                background-color: rgba(60, 60, 60, 180);
                color: white;
                border: 1px solid gray;
                border-radius: 3px;
                font-size: 16px;
            }
            QPushButton:hover {
                background-color: rgba(80, 80, 80, 200);
            }
        """)
        self.maximize_button.clicked.connect(self._toggle_maximize)

        layout.addWidget(self.video_label)

        # Position button as overlay in top-right corner
        self.maximize_button.setParent(self.video_label)
        self.maximize_button.move(self.video_label.width() - 40, 10)
        self.maximize_button.raise_()

        self.setLayout(layout)

    @pyqtSlot(np.ndarray)
    def update_frame(self, frame: np.ndarray):
        """
        Update the displayed frame.

        Args:
            frame: Numpy array containing the image (BGR format from OpenCV)
        """
        if frame is None or frame.size == 0:
            return

        # Convert numpy array to QPixmap
        pixmap = numpy_to_qpixmap(frame)

        # Scale to fit the label while maintaining aspect ratio
        scaled_pixmap = scale_qpixmap(
            pixmap, self.video_label.width(), self.video_label.height()
        )

        # Display the frame
        self.video_label.setPixmap(scaled_pixmap)

    def resizeEvent(self, event):
        """Handle widget resize events to scale the video feed."""
        super().resizeEvent(event)
        # Re-scale the current frame if one is displayed
        if not self.video_label.pixmap() or self.video_label.pixmap().isNull():
            return

        scaled_pixmap = scale_qpixmap(
            self.video_label.pixmap(), self.video_label.width(), self.video_label.height()
        )
        self.video_label.setPixmap(scaled_pixmap)

        # Reposition maximize button in top-right corner
        self.maximize_button.move(self.video_label.width() - 40, 10)

    def _toggle_maximize(self):
        """Toggle maximize/minimize state."""
        self.is_maximized = not self.is_maximized

        # Update button appearance
        if self.is_maximized:
            self.maximize_button.setText("⛶")  # Restore icon
            self.maximize_button.setToolTip("Restore video (or double-click video)")
        else:
            self.maximize_button.setText("⛶")  # Maximize icon
            self.maximize_button.setToolTip("Maximize video (or double-click video)")

        # Emit signal for MainWindow to handle layout changes
        self.maximize_toggled.emit(self.is_maximized)

    def _on_double_click(self, event):
        """Handle double-click on video to toggle maximize."""
        self._toggle_maximize()
