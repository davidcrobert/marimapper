"""
Camera exposure and settings control.

Uses OpenCV briefly to apply camera settings which persist on the hardware
after the OpenCV handle is released. This allows FFmpeg to capture frames
with the desired settings.
"""
import cv2
import platform
import logging
import time
from typing import Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class CameraSettings:
    """Stores camera settings for restoration."""

    def __init__(self, autofocus: Optional[int] = None, focus: Optional[int] = None,
                 exposure_mode: Optional[int] = None, exposure: Optional[int] = None,
                 gain: Optional[int] = None):
        """
        Initialize camera settings.

        Args:
            autofocus: Autofocus mode
            focus: Focus value
            exposure_mode: Exposure mode (manual/auto)
            exposure: Exposure value
            gain: Gain value
        """
        self.autofocus = autofocus
        self.focus = focus
        self.exposure_mode = exposure_mode
        self.exposure = exposure
        self.gain = gain


class ExposureController:
    """
    Controls camera exposure and settings using OpenCV.

    Opens camera briefly with OpenCV to apply settings, then releases.
    Settings persist on camera hardware, allowing FFmpeg to capture with
    those settings.
    """

    def __init__(self, device_identifier: str):
        """
        Initialize exposure controller.

        Args:
            device_identifier: Platform-specific device identifier
        """
        self.device_identifier = device_identifier
        self.platform = platform.system()
        self.default_settings: Optional[CameraSettings] = None

        logger.debug(f"ExposureController initialized for {device_identifier}")

    def capture_default_settings(self) -> bool:
        """
        Capture the current camera settings as defaults.

        Returns:
            True if successful, False otherwise
        """
        try:
            cap = self._open_camera()
            if cap is None:
                return False

            self.default_settings = CameraSettings(
                autofocus=int(cap.get(cv2.CAP_PROP_AUTOFOCUS)),
                focus=int(cap.get(cv2.CAP_PROP_FOCUS)),
                exposure_mode=int(cap.get(cv2.CAP_PROP_AUTO_EXPOSURE)),
                exposure=int(cap.get(cv2.CAP_PROP_EXPOSURE)),
                gain=int(cap.get(cv2.CAP_PROP_GAIN))
            )

            cap.release()
            logger.debug("Captured default camera settings")
            return True

        except Exception as e:
            logger.warning(f"Failed to capture default settings: {e}")
            return False

    def set_dark_mode(self, exposure: int) -> bool:
        """
        Set camera to dark mode for LED detection.

        Applies minimal exposure, disables autofocus, and sets manual exposure mode.

        Args:
            exposure: Exposure value (negative for darker)

        Returns:
            True if successful, False otherwise
        """
        logger.debug(f"Setting camera to dark mode with exposure={exposure}")

        return self.apply_settings(
            autofocus=0,
            focus=0,
            exposure_mode=0,  # Manual mode
            gain=0,
            exposure=exposure
        )

    def set_bright_mode(self) -> bool:
        """
        Reset camera to normal/bright mode.

        Restores default settings if they were captured, otherwise
        sets reasonable defaults.

        Returns:
            True if successful, False otherwise
        """
        logger.debug("Setting camera to bright mode")

        if self.default_settings is not None:
            # Restore captured defaults
            return self.apply_settings(
                autofocus=self.default_settings.autofocus,
                focus=self.default_settings.focus,
                exposure_mode=self.default_settings.exposure_mode,
                gain=self.default_settings.gain,
                exposure=self.default_settings.exposure
            )
        else:
            # Use reasonable defaults
            return self.apply_settings(
                autofocus=1,  # Auto
                exposure_mode=3,  # Auto exposure
                gain=0,
                exposure=0
            )

    def apply_settings(self, autofocus: Optional[int] = None, focus: Optional[int] = None,
                       exposure_mode: Optional[int] = None, gain: Optional[int] = None,
                       exposure: Optional[int] = None) -> bool:
        """
        Apply camera settings.

        Opens camera briefly with OpenCV, applies settings, and releases.
        Settings persist on camera hardware after release.

        Args:
            autofocus: Autofocus mode (0=off, 1=on)
            focus: Focus value
            exposure_mode: Exposure mode (0=manual, 1=auto, 3=aperture priority)
            gain: Gain value
            exposure: Exposure value

        Returns:
            True if successful, False otherwise
        """
        try:
            cap = self._open_camera()
            if cap is None:
                return False

            success = True

            # Apply each setting if provided
            if autofocus is not None:
                if not cap.set(cv2.CAP_PROP_AUTOFOCUS, autofocus):
                    logger.debug(f"Failed to set autofocus to {autofocus}")
                    success = False

            if focus is not None:
                if not cap.set(cv2.CAP_PROP_FOCUS, focus):
                    logger.debug(f"Failed to set focus to {focus}")
                    success = False

            if exposure_mode is not None:
                if not cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, exposure_mode):
                    logger.debug(f"Failed to set exposure mode to {exposure_mode}")
                    success = False

            if gain is not None:
                if not cap.set(cv2.CAP_PROP_GAIN, gain):
                    logger.debug(f"Failed to set gain to {gain}")
                    success = False

            if exposure is not None:
                if not cap.set(cv2.CAP_PROP_EXPOSURE, exposure):
                    logger.debug(f"Failed to set exposure to {exposure}")
                    success = False

            # Give camera time to apply settings
            time.sleep(0.1)

            # Release immediately - settings persist on hardware
            cap.release()

            # Small delay to ensure camera releases
            time.sleep(0.1)

            if success:
                logger.debug("Camera settings applied successfully")
            else:
                logger.warning("Some camera settings failed to apply")

            return success

        except Exception as e:
            logger.error(f"Error applying camera settings: {e}")
            return False

    def _open_camera(self) -> Optional[cv2.VideoCapture]:
        """
        Open camera with OpenCV using appropriate capture method.

        Returns:
            VideoCapture object if successful, None otherwise
        """
        # Determine OpenCV device identifier
        opencv_device = self._get_opencv_device_id()

        if opencv_device is None:
            logger.error("Could not determine OpenCV device ID")
            return None

        # Try different capture methods
        if self.platform == "Windows":
            capture_methods = [cv2.CAP_DSHOW]
        elif self.platform == "Linux":
            capture_methods = [cv2.CAP_V4L2]
        elif self.platform == "Darwin":
            capture_methods = [cv2.CAP_AVFOUNDATION]
        else:
            capture_methods = [cv2.CAP_ANY]

        for method in capture_methods:
            try:
                cap = cv2.VideoCapture(opencv_device, method)
                if cap.isOpened():
                    logger.debug(f"Opened camera with method {method}")
                    return cap
            except Exception as e:
                logger.debug(f"Failed to open with method {method}: {e}")
                continue

        logger.error(f"Failed to open camera {self.device_identifier}")
        return None

    def _get_opencv_device_id(self):
        """
        Convert device identifier to OpenCV-compatible device ID.

        Returns:
            Device ID suitable for cv2.VideoCapture
        """
        if self.platform == "Linux":
            # Linux uses device paths like /dev/video0
            # OpenCV can use the path directly or extract the number
            if self.device_identifier.startswith("/dev/video"):
                # Try using the path directly first
                return self.device_identifier
            else:
                return None

        elif self.platform == "Windows":
            # Windows: Try to find the device index for the name
            # This is tricky - we need to probe devices
            return self._find_windows_device_index()

        elif self.platform == "Darwin":
            # macOS: device identifier is usually already an index
            try:
                return int(self.device_identifier)
            except ValueError:
                # If not an index, we need to search
                return self._find_macos_device_index()

        return None

    def _find_windows_device_index(self) -> Optional[int]:
        """
        Find Windows device index by probing.

        This is necessary because Windows uses device names, but OpenCV
        needs indices.

        Returns:
            Device index if found, None otherwise
        """
        # Try up to 10 devices
        for i in range(10):
            try:
                cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
                if cap.isOpened():
                    # Try to match device name
                    # Unfortunately, OpenCV doesn't expose device name easily
                    # So we'll just try each index
                    cap.release()
                    time.sleep(0.05)
                    # Return first index that works as a fallback
                    # User may need to specify correct index manually
                    return i
            except Exception:
                continue

        logger.warning(f"Could not find Windows device index for {self.device_identifier}")
        return 0  # Fallback to first device

    def _find_macos_device_index(self) -> Optional[int]:
        """
        Find macOS device index.

        Returns:
            Device index if found, None otherwise
        """
        # For macOS, we'd need to parse AVFoundation device list
        # For now, fallback to first device
        logger.warning(f"Could not determine macOS device index for {self.device_identifier}")
        return 0
