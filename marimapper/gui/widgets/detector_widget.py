"""
Detector video display widget for MariMapper GUI.

Displays the live camera feed from the detector process with LED detections.
"""

import numpy as np
from PyQt6.QtWidgets import QWidget, QLabel, QVBoxLayout, QPushButton
from PyQt6.QtCore import Qt, pyqtSlot, pyqtSignal, QPoint
from PyQt6.QtGui import QPixmap, QPainter, QPen, QColor, QImage
import cv2

from marimapper.gui.utils.image_utils import numpy_to_qpixmap, scale_qpixmap


class DetectorWidget(QWidget):
    """Widget for displaying the detector camera feed."""

    # Signal emitted when maximize/minimize is toggled
    maximize_toggled = pyqtSignal(bool)  # True = maximize, False = restore
    # Mask signals
    mask_updated = pyqtSignal(object)  # Emits numpy array when mask changes
    mask_cleared = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_maximized = False

        # Mask painting state
        self.painting_mode = False  # Toggle painting on/off
        self.is_painting = False  # Currently dragging
        self.brush_size = 20  # Brush radius in pixels
        self.mask_overlay = None  # QPixmap with alpha for display
        self.last_paint_point = None  # For smooth line drawing
        self.show_mask = True  # Toggle mask visibility
        self.base_frame = None  # Store base video frame

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

        # Store base frame
        self.base_frame = scaled_pixmap

        # Apply mask overlay if visible
        if self.show_mask and self.mask_overlay is not None:
            result = scaled_pixmap.copy()
            painter = QPainter(result)
            scaled_overlay = self.mask_overlay.scaled(
                result.size(),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(0, 0, scaled_overlay)
            painter.end()
            self.video_label.setPixmap(result)
        else:
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

    def mousePressEvent(self, event):
        """Handle mouse press for painting."""
        if self.painting_mode and event.button() == Qt.MouseButton.LeftButton:
            # Convert event position to video_label coordinates
            pos = self.video_label.mapFrom(self, event.position().toPoint())
            if self.video_label.rect().contains(pos):
                self.is_painting = True
                self.last_paint_point = pos
                self.paint_mask_at(pos)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """Handle mouse drag for painting."""
        if self.is_painting and self.painting_mode:
            pos = self.video_label.mapFrom(self, event.position().toPoint())
            if self.video_label.rect().contains(pos):
                # Draw line from last point to current for smooth stroke
                self.paint_mask_line(self.last_paint_point, pos)
                self.last_paint_point = pos
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """Handle mouse release - end painting."""
        if self.is_painting and event.button() == Qt.MouseButton.LeftButton:
            self.is_painting = False
            # Emit signal with updated mask data
            self.mask_updated.emit(self.get_mask_as_numpy())
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paint_mask_at(self, pos: QPoint):
        """Paint circular brush stroke at position."""
        if self.mask_overlay is None:
            # Initialize overlay matching video label size
            size = self.video_label.size()
            self.mask_overlay = QPixmap(size)
            self.mask_overlay.fill(Qt.GlobalColor.transparent)

        painter = QPainter(self.mask_overlay)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Semi-transparent red for masked regions
        brush_color = QColor(255, 0, 0, 100)  # RGBA with 100/255 opacity
        painter.setBrush(brush_color)
        painter.setPen(Qt.PenStyle.NoPen)

        # Draw circle at position
        painter.drawEllipse(pos, self.brush_size, self.brush_size)
        painter.end()

        # Redraw video with overlay
        self.update_display()

    def paint_mask_line(self, start: QPoint, end: QPoint):
        """Paint line between two points for smooth stroke."""
        if self.mask_overlay is None:
            return

        painter = QPainter(self.mask_overlay)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        brush_color = QColor(255, 0, 0, 100)
        painter.setBrush(brush_color)
        painter.setPen(
            QPen(
                brush_color,
                self.brush_size * 2,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
        )

        painter.drawLine(start, end)
        painter.end()

        self.update_display()

    def update_display(self):
        """Redraw video frame with mask overlay."""
        if self.base_frame is None:
            return

        # Get current video frame
        base_pixmap = self.base_frame.copy()

        # Composite mask overlay if visible
        if self.show_mask and self.mask_overlay is not None:
            painter = QPainter(base_pixmap)
            # Scale overlay to match current video size if needed
            scaled_overlay = self.mask_overlay.scaled(
                base_pixmap.size(),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(0, 0, scaled_overlay)
            painter.end()

        self.video_label.setPixmap(base_pixmap)

    def get_mask_as_numpy(self):
        """Convert mask overlay to binary numpy array (0=ignore, 255=detect)."""
        if self.mask_overlay is None:
            return None

        # Convert QPixmap to QImage
        image = self.mask_overlay.toImage()

        # Convert to RGBA format if needed
        image = image.convertToFormat(QImage.Format.Format_RGBA8888)

        # Extract to numpy array (PyQt6 compatible way)
        width = image.width()
        height = image.height()
        ptr = image.constBits()
        ptr.setsize(image.sizeInBytes())
        arr = np.frombuffer(ptr, np.uint8).reshape((height, width, 4))

        # Extract alpha channel and threshold
        # Alpha > 0 means painted (ignore), so invert: 0 where painted, 255 elsewhere
        alpha = arr[:, :, 3]
        mask = np.where(alpha > 0, 0, 255).astype(np.uint8)

        return mask

    def set_mask_from_numpy(self, mask):
        """Load mask from numpy array and update display overlay."""
        if mask is None:
            self.mask_overlay = None
            self.update_display()
            return

        # Create QPixmap overlay from mask
        height, width = mask.shape
        self.mask_overlay = QPixmap(width, height)
        self.mask_overlay.fill(Qt.GlobalColor.transparent)

        painter = QPainter(self.mask_overlay)
        # Convert mask to red overlay: 0 (masked) -> red, 255 (detect) -> transparent
        for y in range(height):
            for x in range(width):
                if mask[y, x] == 0:  # Masked pixel
                    painter.setPen(QColor(255, 0, 0, 100))
                    painter.drawPoint(x, y)
        painter.end()

        self.update_display()

    def set_painting_mode(self, enabled: bool):
        """Enable or disable painting mode."""
        self.painting_mode = enabled
        if enabled:
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def set_brush_size(self, size: int):
        """Set brush size."""
        self.brush_size = size

    def set_mask_visibility(self, visible: bool):
        """Toggle mask visibility."""
        self.show_mask = visible
        self.update_display()
