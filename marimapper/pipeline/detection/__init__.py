"""
Detection package - LED detection algorithms and worker processes.

This package provides:
- Pure detection algorithms (find_led_in_image, masking, thresholding)
- Camera control helpers (dark mode, preview mode)
- Detection worker processes for single and multi-camera setups
- Command schemas for coordinating detection across cameras

Architecture:
- algorithms.py: Pure functions for LED detection (no I/O, testable)
- camera_control.py: Camera mode switching (dark/bright exposure)
- worker.py: Process-based worker that responds to coordinator commands
- commands.py: Command enums and message schemas

Usage:
    from marimapper.pipeline.detection import find_led_in_image, DetectionWorker
"""

from .algorithms import (
    find_led_in_image,
    draw_led_detections,
    contour_brightness,
)

from .camera_control import (
    set_cam_dark,
    set_cam_default,
)

from .worker import DetectionWorker

from .commands import (
    DetectionCommand,
    DetectionResult,
    DetectionPosition,
    MaskData,
    create_command,
    create_result,
)

__all__ = [
    # Algorithms
    "find_led_in_image",
    "draw_led_detections",
    "contour_brightness",
    # Camera control
    "set_cam_dark",
    "set_cam_default",
    # Worker
    "DetectionWorker",
    # Commands
    "DetectionCommand",
    "DetectionResult",
    "DetectionPosition",
    "MaskData",
    "create_command",
    "create_result",
]
