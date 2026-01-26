"""
Main Camera interface for MariMapper.

Uses composition with VideoSource and SettingsController strategies
to support USB, AXIS, and hybrid camera configurations.
"""
import logging
from typing import Optional
import numpy as np

from .video_source import VideoSource
from .settings_controller import SettingsController

logger = logging.getLogger(__name__)


class Camera:
    """
    Camera interface for MariMapper.

    Composes VideoSource (frame capture) and SettingsController (exposure/focus)
    to support USB, AXIS, and hybrid camera configurations.
    """

    def __init__(
        self,
        video_source: VideoSource,
        settings_controller: SettingsController,
        name: str = "Camera"
    ):
        """
        Initialize camera with explicit video source and settings controller.

        Args:
            video_source: Strategy for capturing video frames
            settings_controller: Strategy for controlling camera settings
            name: Human-readable name for logging
        """
        self.name = name
        self._video_source = video_source
        self._settings_controller = settings_controller

        # Start video capture
        self._video_source.start()

        # Capture default settings
        self._settings_controller.capture_defaults()

        logger.info(f"Camera '{name}' initialized")

    @classmethod
    def from_legacy_config(
        cls,
        device_name: Optional[str] = None,
        axis_config: Optional[dict] = None
    ) -> "Camera":
        """
        Factory method for backwards compatibility with existing code.

        Args:
            device_name: USB camera device name
            axis_config: Dict with 'host', 'username', 'password' for AXIS camera

        Returns:
            Configured Camera instance
        """
        from .camera_config import convert_legacy_config

        if axis_config is not None:
            config = convert_legacy_config(axis_config)
        elif device_name is not None:
            config = convert_legacy_config({"device": device_name})
        else:
            raise ValueError("Either device_name or axis_config must be provided")

        return cls(
            video_source=config.video_source,
            settings_controller=config.settings_controller,
            name=config.name
        )

    @classmethod
    def from_config(cls, config: "CameraConfig") -> "Camera":
        """
        Create Camera from parsed CameraConfig.

        Args:
            config: Parsed camera configuration

        Returns:
            Configured Camera instance
        """
        # Create video source and settings controller in this subprocess
        video_source = config.create_video_source()
        settings_controller = config.create_settings_controller()

        return cls(
            video_source=video_source,
            settings_controller=settings_controller,
            name=config.name
        )

    def read(self) -> np.ndarray:
        """
        Capture and return a single frame.

        Returns:
            BGR frame as numpy array

        Raises:
            Exception: If frame capture fails
        """
        return self._video_source.read()

    def eat(self, count: int = 30) -> None:
        """
        Discard frames to flush camera buffer.

        Important after changing camera settings to ensure fresh frames.

        Args:
            count: Number of frames to discard
        """
        self._video_source.flush(count)

    def reset(self) -> None:
        """Reset camera to default settings."""
        self._settings_controller.set_bright_mode()

    def set_dark_mode_level(self, level: float) -> bool:
        """
        Set camera to dark mode with specified intensity level.

        Args:
            level: Darkness level (0-1), where 0 is minimal darkening
                   and 1 is maximum darkening

        Returns:
            True if successful, False otherwise
        """
        return self._settings_controller.set_dark_mode_level(level)

    def set_bright_mode_level(self, level: float) -> bool:
        """
        Set camera to bright mode with specified intensity level.

        Args:
            level: Brightness level (0-1), where 0 is dim
                   and 1 is maximum brightness

        Returns:
            True if successful, False otherwise
        """
        return self._settings_controller.set_bright_mode_level(level)

    def set_exposure(self, exposure: int) -> bool:
        """
        Set camera exposure value.

        Args:
            exposure: Exposure value (negative for darker)

        Returns:
            True if successful, False otherwise
        """
        if exposure < 0:
            return self._settings_controller.set_dark_mode(exposure)
        else:
            return self._settings_controller.set_bright_mode()

    def set_autofocus(self, mode: int, focus: int = 0) -> None:
        """
        Control autofocus settings.

        Args:
            mode: Autofocus mode (0=off, 1=on)
            focus: Focus value
        """
        # Only OpenCV controller supports this; others ignore
        if hasattr(self._settings_controller, '_controller'):
            # OpenCVSettingsController wraps ExposureController
            self._settings_controller._controller.apply_settings(autofocus=mode, focus=focus)

    def set_exposure_mode(self, mode: int) -> None:
        """
        Set exposure mode (auto/manual).

        Args:
            mode: Exposure mode (0=manual, 1=auto, 3=aperture priority)
        """
        # Only OpenCV controller supports this
        if hasattr(self._settings_controller, '_controller'):
            self._settings_controller._controller.apply_settings(exposure_mode=mode)

    def set_gain(self, gain: int) -> None:
        """
        Set camera gain.

        Args:
            gain: Gain value
        """
        # Only OpenCV controller supports this
        if hasattr(self._settings_controller, '_controller'):
            self._settings_controller._controller.apply_settings(gain=gain)

    def get_af_mode(self) -> int:
        """Get autofocus mode (for compatibility)."""
        return 0

    def get_focus(self) -> int:
        """Get focus value (for compatibility)."""
        return 0

    def get_exposure_mode(self) -> int:
        """Get exposure mode (for compatibility)."""
        return 0

    def get_exposure(self) -> int:
        """Get exposure value (for compatibility)."""
        return 0

    def get_gain(self) -> int:
        """Get gain value (for compatibility)."""
        return 0

    def release(self) -> None:
        """Release camera resources."""
        self._video_source.stop()
        logger.info(f"Camera '{self.name}' released")

    def __del__(self):
        """Cleanup on deletion."""
        try:
            self.release()
        except Exception:
            pass
