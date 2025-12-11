"""
Camera module for MariMapper.

Provides camera interface with support for USB cameras (via FFmpeg)
and Axis IP cameras (via OpenCV MJPEG stream).
"""
from .camera import Camera
from .device_listing import list_available_cameras, find_camera_by_name, CameraDevice
from .exposure_control import CameraSettings

__all__ = [
    "Camera",
    "list_available_cameras",
    "find_camera_by_name",
    "CameraDevice",
    "CameraSettings",
]
