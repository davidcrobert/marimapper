"""
Detector video display widget for MariMapper GUI.

Displays the live camera feed from the detector process with LED detections.
"""

import numpy as np
from PyQt6.QtWidgets import QWidget, QLabel, QVBoxLayout
from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QPixmap

from marimapper.gui.utils.image_utils import numpy_to_qpixmap, scale_qpixmap


class DetectorWidget(QWidget):
    """Widget for displaying the detector camera feed."""

    def __init__(self, parent=None):
        super().__init__(parent)
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

        layout.addWidget(self.video_label)
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
