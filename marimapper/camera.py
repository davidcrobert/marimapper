import cv2
from multiprocessing import get_logger
import requests
from requests.auth import HTTPDigestAuth

logger = get_logger()


class CameraSettings:

    def __init__(self, camera):
        self.af_mode = camera.get_af_mode()
        self.focus = camera.get_focus()
        self.exposure_mode = camera.get_exposure_mode()
        self.exposure = camera.get_exposure()
        self.gain = camera.get_gain()

    def apply(self, camera):
        camera.set_autofocus(self.af_mode, self.focus)
        camera.set_exposure_mode(self.exposure_mode)
        camera.set_gain(self.gain)
        camera.set_exposure(self.exposure)


class Camera:

    def __init__(self, device_id=None, axis_config=None):
        """
        Initialize camera with either a device_id (for USB/webcam) or axis_config (for Axis IP camera).

        Args:
            device_id: Integer device ID for USB/webcam (e.g., 0, 1)
            axis_config: Dict with keys 'host', 'username', 'password' for Axis IP camera
        """
        if axis_config is not None:
            # Axis IP camera mode
            self.is_axis_camera = True
            self.device_id = None
            self.axis_host = axis_config['host']
            self.axis_username = axis_config['username']
            self.axis_password = axis_config['password']
            self.axis_vapix_url = f"http://{self.axis_host}/axis-cgi/param.cgi"
            stream_url = f"http://{self.axis_username}:{self.axis_password}@{self.axis_host}/axis-cgi/mjpg/video.cgi"

            logger.info(f"Connecting to Axis camera at {self.axis_host} ...")
            self.device = cv2.VideoCapture(stream_url)

            if not self.device.isOpened():
                raise RuntimeError(f"Failed to connect to Axis camera at {self.axis_host}")

            logger.info(f"Successfully connected to Axis camera at {self.axis_host}")

            # Axis cameras don't support property changes via OpenCV, so skip default settings
            self.default_settings = None
        else:
            # USB/webcam mode
            self.is_axis_camera = False
            logger.info(f"Connecting to device {device_id} ...")
            self.device_id = device_id

            for capture_method in [cv2.CAP_DSHOW, cv2.CAP_V4L2, cv2.CAP_ANY]:
                self.device = cv2.VideoCapture(device_id, capture_method)
                if self.device.isOpened():
                    logger.debug(
                        f"Connected to device {device_id} with capture method {capture_method}"
                    )
                    break

            if not self.device.isOpened():
                raise RuntimeError(f"Failed to connect to camera {device_id}")

            self.default_settings = CameraSettings(self)

    def reset(self):
        if self.is_axis_camera:
            # For Axis cameras, reset means opening the iris (bright mode)
            logger.debug("Resetting Axis camera to bright mode")
            self._set_axis_iris(0)
        elif self.default_settings is not None:
            self.default_settings.apply(self)

    def _vapix_request(self, params):
        """Make a VAPIX API request with authentication fallback."""
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

    def _set_axis_iris(self, position: int):
        """
        Set Axis camera iris position via VAPIX API.

        Args:
            position: Iris position 0-100 (0=open/bright, 100=closed/dark)
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

    def get_af_mode(self):
        return int(self.device.get(cv2.CAP_PROP_AUTOFOCUS))

    def get_focus(self):
        return int(self.device.get(cv2.CAP_PROP_FOCUS))

    def get_exposure_mode(self):
        return int(self.device.get(cv2.CAP_PROP_AUTO_EXPOSURE))

    def get_exposure(self):
        return int(self.device.get(cv2.CAP_PROP_EXPOSURE))

    def get_gain(self):
        return int(self.device.get(cv2.CAP_PROP_GAIN))

    def set_autofocus(self, mode, focus=0):
        if self.is_axis_camera:
            logger.debug("Skipping autofocus setting for Axis camera")
            return

        logger.debug(f"Setting autofocus to mode {mode} with focus {focus}")

        if not self.device.set(cv2.CAP_PROP_AUTOFOCUS, mode):
            logger.info(f"Failed to set autofocus to {mode}")

        if not self.device.set(cv2.CAP_PROP_FOCUS, focus):
            logger.info(f"Failed to set focus to {focus}")

    def set_exposure_mode(self, mode):
        if self.is_axis_camera:
            logger.debug("Skipping exposure mode setting for Axis camera")
            return

        logger.debug(f"Setting exposure to mode {mode}")

        if not self.device.set(cv2.CAP_PROP_AUTO_EXPOSURE, mode):
            logger.info(f"Failed to put camera into manual exposure mode {mode}")

    def set_gain(self, gain):
        if self.is_axis_camera:
            logger.debug("Skipping gain setting for Axis camera")
            return

        logger.debug(f"Setting gain to {gain}")

        if not self.device.set(cv2.CAP_PROP_GAIN, gain):
            logger.info(f"failed to set camera gain to {gain}")

    def set_exposure(self, exposure: int) -> bool:
        if self.is_axis_camera:
            # For Axis cameras, use VAPIX API to control iris position
            # Negative exposure values = dark mode -> iris closed (Position=100)
            # Zero/positive exposure = bright mode -> iris open (Position=0)
            if exposure < 0:
                # Dark mode for LED detection
                logger.debug(f"Setting Axis camera to dark mode (exposure={exposure})")
                return self._set_axis_iris(100)
            else:
                # Bright/normal mode
                logger.debug(f"Setting Axis camera to bright mode (exposure={exposure})")
                return self._set_axis_iris(0)

        logger.debug(f"Setting exposure to {exposure}")

        if not self.device.set(cv2.CAP_PROP_EXPOSURE, exposure):
            logger.info(f"Failed to set exposure to {exposure}")
            return False

        return True

    def eat(self, count=30):
        for _ in range(count):
            self.read()

    def read(self):
        ret_val, image = self.device.read()
        if not ret_val:
            raise Exception("Failed to read image")

        return image
