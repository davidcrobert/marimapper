import cv2
from multiprocessing import get_logger

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
            host = axis_config['host']
            username = axis_config['username']
            password = axis_config['password']
            stream_url = f"http://{username}:{password}@{host}/axis-cgi/mjpg/video.cgi"

            logger.info(f"Connecting to Axis camera at {host} ...")
            self.device = cv2.VideoCapture(stream_url)

            if not self.device.isOpened():
                raise RuntimeError(f"Failed to connect to Axis camera at {host}")

            logger.info(f"Successfully connected to Axis camera at {host}")

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
        if self.default_settings is not None:
            self.default_settings.apply(self)

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
            logger.debug("Skipping exposure setting for Axis camera")
            return True

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
