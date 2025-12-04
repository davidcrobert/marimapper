"""
Image conversion utilities for MariMapper GUI.

Provides functions to convert between OpenCV (numpy) and Qt image formats.
"""

import numpy as np
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtCore import Qt


def numpy_to_qimage(image: np.ndarray) -> QImage:
    """
    Convert numpy array (OpenCV format) to QImage.

    Args:
        image: Numpy array in BGR format (OpenCV default)

    Returns:
        QImage object ready for display in Qt widgets

    Note:
        OpenCV uses BGR color order, Qt expects RGB.
        This function handles the conversion.
    """
    if image is None or image.size == 0:
        # Return empty image if input is invalid
        return QImage()

    # Get image dimensions
    height, width = image.shape[:2]

    # Handle different image formats
    if len(image.shape) == 2:
        # Grayscale image
        bytes_per_line = width
        q_image = QImage(
            image.data, width, height, bytes_per_line, QImage.Format.Format_Grayscale8
        )
    elif len(image.shape) == 3 and image.shape[2] == 3:
        # BGR color image (OpenCV default)
        # Convert BGR to RGB
        rgb_image = np.ascontiguousarray(image[:, :, ::-1])
        bytes_per_line = 3 * width
        q_image = QImage(
            rgb_image.data, width, height, bytes_per_line, QImage.Format.Format_RGB888
        )
    elif len(image.shape) == 3 and image.shape[2] == 4:
        # BGRA color image
        # Convert BGRA to RGBA
        rgba_image = np.ascontiguousarray(image[:, :, [2, 1, 0, 3]])
        bytes_per_line = 4 * width
        q_image = QImage(
            rgba_image.data,
            width,
            height,
            bytes_per_line,
            QImage.Format.Format_RGBA8888,
        )
    else:
        raise ValueError(f"Unsupported image format: shape={image.shape}")

    # Make a copy to avoid memory issues when original numpy array is deleted
    return q_image.copy()


def numpy_to_qpixmap(image: np.ndarray) -> QPixmap:
    """
    Convert numpy array (OpenCV format) to QPixmap.

    Args:
        image: Numpy array in BGR format (OpenCV default)

    Returns:
        QPixmap object ready for display in QLabel

    Note:
        This is a convenience wrapper around numpy_to_qimage.
    """
    return QPixmap.fromImage(numpy_to_qimage(image))


def scale_qpixmap(pixmap: QPixmap, width: int, height: int) -> QPixmap:
    """
    Scale a QPixmap to fit within given dimensions while maintaining aspect ratio.

    Args:
        pixmap: QPixmap to scale
        width: Maximum width
        height: Maximum height

    Returns:
        Scaled QPixmap
    """
    return pixmap.scaled(
        width, height, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
    )
