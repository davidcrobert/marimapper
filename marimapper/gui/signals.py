"""
Custom Qt signals for MariMapper GUI.

These signals enable thread-safe communication between the Scanner processes
and the GUI main thread.
"""

from PyQt6.QtCore import QObject, pyqtSignal
import numpy as np


class MariMapperSignals(QObject):
    """Custom signals for MariMapper GUI communication."""

    # Frame from detector process (numpy array)
    frame_ready = pyqtSignal(np.ndarray)
    frame_ready_multi = pyqtSignal(int, np.ndarray)  # camera_index, frame

    # LED detection signals
    led_detected = pyqtSignal(object)  # LED2D object
    led_skipped = pyqtSignal(int)  # LED ID that was skipped

    # Scan progress signals
    scan_started = pyqtSignal(int, int, int)  # led_from, led_to, view_id
    scan_completed = pyqtSignal(int)  # view_id
    scan_failed = pyqtSignal(str)  # error message
    view_deleted = pyqtSignal(int)  # view_id (due to camera movement)

    # 3D reconstruction signals
    reconstruction_updated = pyqtSignal(dict)  # LED ID → LEDInfo status dict
    points_3d_updated = pyqtSignal(list)  # List of LED3D objects

    # Process health signals
    process_crashed = pyqtSignal(str)  # process name
    all_processes_healthy = pyqtSignal()

    # Log message signal
    log_message = pyqtSignal(str, str)  # (level, message) where level = info/warning/error
