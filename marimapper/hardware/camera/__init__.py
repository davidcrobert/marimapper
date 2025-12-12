"""
Camera hardware abstraction.

Re-exports camera interfaces from the marimapper.camera module.
This will eventually replace the root-level camera module once migration is complete.
"""

# For now, re-export from the existing camera module for compatibility
from marimapper.camera.camera import Camera
from marimapper.camera.camera_config import CameraConfig as LegacyCameraConfig, parse_camera_config_file
from marimapper.camera.video_source import VideoSource, FFmpegVideoSource, MJPEGVideoSource
from marimapper.camera.settings_controller import (
    SettingsController,
    OpenCVSettingsController,
    VAPIXSettingsController,
    NoOpSettingsController
)

__all__ = [
    "Camera",
    "LegacyCameraConfig",
    "parse_camera_config_file",
    "VideoSource",
    "FFmpegVideoSource",
    "MJPEGVideoSource",
    "SettingsController",
    "OpenCVSettingsController",
    "VAPIXSettingsController",
    "NoOpSettingsController",
]
