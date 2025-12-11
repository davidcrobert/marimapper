"""
Main Camera interface for MariMapper.

Provides unified camera interface for both USB cameras (via FFmpeg)
and Axis IP cameras (via OpenCV MJPEG stream).
"""
import cv2
import logging
import requests
from requests.auth import HTTPDigestAuth
from typing import Optional
import numpy as np

from .ffmpeg_capture import FFmpegCapture
from .exposure_control import ExposureController, CameraSettings
from .device_listing import find_camera_by_name

logger = logging.getLogger(__name__)


class Camera:
    """
    Camera interface for MariMapper.

    Supports USB cameras (via FFmpeg) and Axis IP cameras (via MJPEG stream).
    Device selection uses device NAMES for USB cameras, not indices.
    """

    def __init__(self, device_name: Optional[str] = None, axis_config: Optional[dict] = None):
        """
        Initialize camera.

        Args:
            device_name: Camera device name (e.g., "22_Cam2" on Windows,
                        "video0" on Linux). Use list_available_cameras() to find available devices.
            axis_config: Dict with 'host', 'username', 'password' for Axis IP camera.
                        If provided, device_name is ignored.
        """
        if axis_config is not None:
            self._init_axis_camera(axis_config)
        elif device_name is not None:
            self._init_usb_camera(device_name)
        else:
            raise ValueError("Either device_name or axis_config must be provided")

    def _init_axis_camera(self, axis_config: dict):
        """Initialize Axis IP camera."""
        self.is_axis_camera = True
        self.device_name = None

        self.axis_host = axis_config['host']
        self.axis_username = axis_config['username']
        self.axis_password = axis_config['password']
        self.axis_vapix_url = f"http://{self.axis_host}/axis-cgi/param.cgi"

        stream_url = f"http://{self.axis_username}:{self.axis_password}@{self.axis_host}/axis-cgi/mjpg/video.cgi"

        logger.info(f"Connecting to Axis camera at {self.axis_host}...")
        self.device = cv2.VideoCapture(stream_url)

        if not self.device.isOpened():
            raise RuntimeError(f"Failed to connect to Axis camera at {self.axis_host}")

        logger.info(f"Successfully connected to Axis camera at {self.axis_host}")

        # Axis cameras don't support property changes via OpenCV
        self.default_settings = None
        self.ffmpeg_capture = None
        self.exposure_controller = None

    def _init_usb_camera(self, device_name: str):
        """Initialize USB camera with FFmpeg."""
        self.is_axis_camera = False
        self.device_name = device_name

        # Try to find camera device
        camera_device = find_camera_by_name(device_name)

        if camera_device is None:
            logger.warning(f"Could not find camera '{device_name}' in device list, using name as-is")
            device_identifier = device_name
        else:
            device_identifier = camera_device.identifier
            logger.info(f"Found camera: {camera_device.name}")

        # Initialize FFmpeg capture
        self.ffmpeg_capture = FFmpegCapture(device_identifier)
        self.ffmpeg_capture.start()

        # Initialize exposure controller
        self.exposure_controller = ExposureController(device_identifier)

        # Capture default settings
        self.exposure_controller.capture_default_settings()

        # OpenCV device not used for USB cameras
        self.device = None

    def read(self) -> np.ndarray:
        """
        Capture and return a single frame.

        Returns:
            BGR frame as numpy array

        Raises:
            Exception: If frame capture fails
        """
        if self.is_axis_camera:
            ret_val, image = self.device.read()
            if not ret_val:
                raise Exception("Failed to read image from Axis camera")
            return image
        else:
            return self.ffmpeg_capture.read()

    def eat(self, count: int = 30) -> None:
        """
        Discard frames to flush camera buffer.

        Important after changing camera settings to ensure fresh frames.

        Args:
            count: Number of frames to discard
        """
        if self.is_axis_camera:
            for _ in range(count):
                self.device.read()
        else:
            self.ffmpeg_capture.flush(count)

    def reset(self) -> None:
        """Reset camera to default settings."""
        if self.is_axis_camera:
            # For Axis cameras, reset means opening the iris (bright mode)
            logger.debug("Resetting Axis camera to bright mode")
            self._set_axis_iris(0)
        else:
            # For USB cameras, restore default settings
            if self.exposure_controller is not None:
                self.exposure_controller.set_bright_mode()

    def set_exposure(self, exposure: int) -> bool:
        """
        Set camera exposure value.

        Args:
            exposure: Exposure value (negative for darker)

        Returns:
            True if successful, False otherwise
        """
        if self.is_axis_camera:
            # For Axis cameras, use VAPIX API to control iris
            if exposure < 0:
                # Dark mode for LED detection
                logger.debug(f"Setting Axis camera to dark mode (exposure={exposure})")
                return self._set_axis_iris(100)
            else:
                # Bright/normal mode
                logger.debug(f"Setting Axis camera to bright mode (exposure={exposure})")
                return self._set_axis_iris(0)
        else:
            # For USB cameras, use exposure controller
            if self.exposure_controller is not None:
                return self.exposure_controller.apply_settings(exposure=exposure)
            return False

    def set_autofocus(self, mode: int, focus: int = 0) -> None:
        """
        Control autofocus settings.

        Args:
            mode: Autofocus mode (0=off, 1=on)
            focus: Focus value
        """
        if self.is_axis_camera:
            logger.debug("Skipping autofocus setting for Axis camera")
            return

        if self.exposure_controller is not None:
            self.exposure_controller.apply_settings(autofocus=mode, focus=focus)

    def set_exposure_mode(self, mode: int) -> None:
        """
        Set exposure mode (auto/manual).

        Args:
            mode: Exposure mode (0=manual, 1=auto, 3=aperture priority)
        """
        if self.is_axis_camera:
            logger.debug("Skipping exposure mode setting for Axis camera")
            return

        if self.exposure_controller is not None:
            self.exposure_controller.apply_settings(exposure_mode=mode)

    def set_gain(self, gain: int) -> None:
        """
        Set camera gain.

        Args:
            gain: Gain value
        """
        if self.is_axis_camera:
            logger.debug("Skipping gain setting for Axis camera")
            return

        if self.exposure_controller is not None:
            self.exposure_controller.apply_settings(gain=gain)

    def get_af_mode(self) -> int:
        """Get autofocus mode (for compatibility)."""
        if self.is_axis_camera and self.device is not None:
            return int(self.device.get(cv2.CAP_PROP_AUTOFOCUS))
        return 0

    def get_focus(self) -> int:
        """Get focus value (for compatibility)."""
        if self.is_axis_camera and self.device is not None:
            return int(self.device.get(cv2.CAP_PROP_FOCUS))
        return 0

    def get_exposure_mode(self) -> int:
        """Get exposure mode (for compatibility)."""
        if self.is_axis_camera and self.device is not None:
            return int(self.device.get(cv2.CAP_PROP_AUTO_EXPOSURE))
        return 0

    def get_exposure(self) -> int:
        """Get exposure value (for compatibility)."""
        if self.is_axis_camera and self.device is not None:
            return int(self.device.get(cv2.CAP_PROP_EXPOSURE))
        return 0

    def get_gain(self) -> int:
        """Get gain value (for compatibility)."""
        if self.is_axis_camera and self.device is not None:
            return int(self.device.get(cv2.CAP_PROP_GAIN))
        return 0

    def release(self) -> None:
        """Release camera resources."""
        if self.is_axis_camera:
            if self.device is not None:
                self.device.release()
        else:
            if self.ffmpeg_capture is not None:
                self.ffmpeg_capture.stop()

    def _vapix_request(self, params: dict):
        """Make a VAPIX API request with authentication fallback (Axis cameras only)."""
        if not self.is_axis_camera:
            return None

        try:
            # Try basic auth first
            resp = requests.get(
                self.axis_vapix_url,
                params=params,
                auth=(self.axis_username, self.axis_password),
                timeout=5,
            )
            # If basic auth fails with 401, try digest auth
            if resp.status_code == 401:
                resp = requests.get(
                    self.axis_vapix_url,
                    params=params,
                    auth=HTTPDigestAuth(self.axis_username, self.axis_password),
                    timeout=5,
                )
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            logger.warning(f"VAPIX API request failed: {exc}")
            return None

    def _set_axis_iris(self, position: int) -> bool:
        """
        Set Axis camera iris position via VAPIX API.

        Args:
            position: Iris position 0-100 (0=open/bright, 100=closed/dark)

        Returns:
            True if successful, False otherwise
        """
        if not self.is_axis_camera:
            return False

        position = max(0, min(100, position))

        resp = self._vapix_request(
            {
                "action": "update",
                "ImageSource.I0.DCIris.Enabled": "no",  # Lock aperture in manual mode
                "ImageSource.I0.DCIris.Position": str(position),
            }
        )

        if resp is not None:
            logger.debug(f"Set Axis iris position to {position} (locked/manual)")
            return True
        else:
            logger.warning(f"Failed to set Axis iris position to {position}")
            return False

    def __del__(self):
        """Cleanup on deletion."""
        try:
            self.release()
        except Exception:
            pass
