"""
Hardware abstraction layer for MariMapper.

Provides stable interfaces for cameras and LED backends, isolating
hardware-specific concerns from the pipeline and UI layers.
"""

from .led_backends import LedBackend, backend_factories, backend_arg_setters
from .camera import (
    Camera,
    VideoSource,
    SettingsController,
    VAPIXSettingsController,
    OpenCVSettingsController,
    NoOpSettingsController,
)

__all__ = [
    # LED Backend
    "LedBackend",
    "backend_factories",
    "backend_arg_setters",
    # Camera
    "Camera",
    "VideoSource",
    "SettingsController",
    "VAPIXSettingsController",
    "OpenCVSettingsController",
    "NoOpSettingsController",
]
