"""
Settings controller strategies for different camera types.

Implements the Strategy pattern to separate settings control logic
from the main Camera class.
"""
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
import logging
import requests
from requests.auth import HTTPDigestAuth

logger = logging.getLogger(__name__)


class SettingsController(ABC):
    """Abstract base class for camera settings control."""

    @abstractmethod
    def set_dark_mode(self, exposure: int) -> bool:
        """Set camera to dark mode for LED detection."""
        pass

    @abstractmethod
    def set_bright_mode(self) -> bool:
        """Reset camera to normal/preview mode."""
        pass

    @abstractmethod
    def capture_defaults(self) -> bool:
        """Capture current settings as defaults (if supported)."""
        pass


class OpenCVSettingsController(SettingsController):
    """Controls settings via OpenCV (for USB cameras)."""

    def __init__(self, device_identifier: str):
        from .exposure_control import ExposureController
        self._controller = ExposureController(device_identifier)

    def set_dark_mode(self, exposure: int) -> bool:
        return self._controller.set_dark_mode(exposure)

    def set_bright_mode(self) -> bool:
        return self._controller.set_bright_mode()

    def capture_defaults(self) -> bool:
        return self._controller.capture_default_settings()


class VAPIXSettingsController(SettingsController):
    """Controls settings via VAPIX API (for AXIS cameras)."""

    # Whitelisted sensor parameters we can save/restore
    SENSOR_PARAMS = {
        "ImageSource.I0.Sensor.Brightness",
        "ImageSource.I0.Sensor.ColorLevel",
        "ImageSource.I0.Sensor.Contrast",
        "ImageSource.I0.Sensor.Sharpness",
        "ImageSource.I0.Sensor.LocalContrast",
        "ImageSource.I0.Sensor.ToneMapping",
        "ImageSource.I0.Sensor.WDR",
        "ImageSource.I0.Sensor.WhiteBalance",
        "ImageSource.I0.Sensor.LowLatencyMode",
        "ImageSource.I0.Sensor.CaptureMode",
    }

    def __init__(self, host: str, username: str = "root", password: str = ""):
        self.host = host
        self.username = username
        self.password = password
        self.param_url = f"http://{host}/axis-cgi/param.cgi"
        self.ptz_url = f"http://{host}/axis-cgi/com/ptz.cgi"

        # Storage for default settings
        self.default_settings: Optional[Dict[str, str]] = None
        self.default_zoom: Optional[str] = None

    def set_dark_mode(self, exposure: int) -> bool:
        """Close iris for dark mode."""
        logger.debug(f"Setting VAPIX camera to dark mode (exposure={exposure})")
        return self._set_iris(100)  # 100 = fully closed/dark

    def set_bright_mode(self) -> bool:
        """Restore saved settings or use defaults."""
        logger.debug("Setting VAPIX camera to bright mode")

        if self.default_settings is None:
            # No saved settings, just open iris
            return self._set_iris(0)

        # Restore all saved settings
        success = True

        # Restore sensor parameters
        for param, value in self.default_settings.items():
            if not self._set_param(param, value):
                logger.warning(f"Failed to restore {param}={value}")
                success = False

        # Restore zoom if we have it
        if self.default_zoom is not None:
            if not self._set_zoom(self.default_zoom):
                logger.warning(f"Failed to restore zoom={self.default_zoom}")
                success = False

        return success

    def capture_defaults(self) -> bool:
        """Capture current VAPIX settings as defaults."""
        logger.debug("Capturing VAPIX default settings")

        # Get all parameters
        resp = self._vapix_request(self.param_url, {"action": "list"})
        if resp is None:
            logger.warning("Failed to retrieve VAPIX parameters")
            return False

        # Parse and store whitelisted parameters
        self.default_settings = {}
        for line in resp.text.splitlines():
            if "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip()

            # Remove "root." prefix if present
            if key.startswith("root."):
                key = key[5:]

            # Store if whitelisted
            if key in self.SENSOR_PARAMS:
                self.default_settings[key] = val

            # Also capture iris position
            if key == "ImageSource.I0.DCIris.Position":
                self.default_settings[key] = val

        # Get current zoom
        zoom_resp = self._ptz_request({"query": "position"})
        if zoom_resp is not None:
            for part in zoom_resp.text.strip().split():
                if part.startswith("zoom="):
                    try:
                        zoom_raw = part.split("=", 1)[1]
                        self.default_zoom = str(int(round(float(zoom_raw))))
                    except (IndexError, ValueError):
                        self.default_zoom = None
                    break

        logger.debug(f"Captured {len(self.default_settings)} VAPIX settings as defaults")
        return True

    def apply_config(self, config_path: str = "axis_config_saved.txt") -> bool:
        """
        Apply all whitelisted parameters + zoom from a config file.

        Also updates the default_settings so that Bright Mode preserves these settings.

        Args:
            config_path: Path to the config file (default: "axis_config_saved.txt")

        Returns:
            True if all settings were applied successfully, False otherwise
        """
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config_lines = f.read().splitlines()
        except OSError as exc:
            logger.error(f"Failed to read config {config_path}: {exc}")
            return False

        applied = 0
        failed = 0
        zoom_val = None
        applied_settings = {}  # Track successfully applied settings

        for line in config_lines:
            if "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip()
            if not key:
                continue

            # Remove "root." prefix if present
            if key.startswith("root."):
                key = key[5:]

            # Handle zoom separately
            if key in ("ptz.zoom", "zoom"):
                try:
                    zoom_val = str(int(round(float(val))))
                except ValueError:
                    zoom_val = val
                continue

            # Apply whitelisted parameters
            if key not in self.SENSOR_PARAMS:
                continue

            if self._set_param(key, val):
                applied += 1
                applied_settings[key] = val
                logger.debug(f"Applied {key}={val}")
            else:
                failed += 1
                logger.warning(f"Failed to apply {key}={val}")

        # Apply zoom if present in config
        if zoom_val is not None:
            if self._set_zoom(zoom_val):
                applied += 1
                logger.debug(f"Applied zoom={zoom_val}")
                # Update default_zoom so Bright Mode preserves it
                self.default_zoom = zoom_val
            else:
                failed += 1
                logger.warning(f"Failed to apply zoom={zoom_val}")

        # Update default_settings with successfully applied settings
        # so that Bright Mode will restore to these values instead of original defaults
        if applied_settings:
            if self.default_settings is None:
                self.default_settings = {}
            self.default_settings.update(applied_settings)
            logger.debug(f"Updated default_settings with {len(applied_settings)} config values")

        logger.info(f"Applied {applied} params, failed {failed} from {config_path}")
        return failed == 0

    def _set_iris(self, position: int) -> bool:
        """Set iris position (0=open, 100=closed)."""
        position = max(0, min(100, position))

        resp = self._vapix_request(
            self.param_url,
            {
                "action": "update",
                "ImageSource.I0.DCIris.Enabled": "no",  # Manual mode
                "ImageSource.I0.DCIris.Position": str(position),
            }
        )

        if resp is not None:
            logger.debug(f"Set VAPIX iris to {position}")
            return True
        else:
            logger.warning(f"Failed to set VAPIX iris to {position}")
            return False

    def _set_param(self, param: str, value: str) -> bool:
        """Set a VAPIX parameter."""
        resp = self._vapix_request(
            self.param_url,
            {"action": "update", param: value}
        )
        return resp is not None

    def _set_zoom(self, zoom: str) -> bool:
        """Set PTZ zoom level."""
        resp = self._ptz_request({"zoom": zoom})
        return resp is not None

    def _vapix_request(self, url: str, params: Dict[str, str]):
        """Make a VAPIX API request with authentication fallback."""
        try:
            # Try basic auth first
            resp = requests.get(
                url,
                params=params,
                auth=(self.username, self.password),
                timeout=5,
            )

            # If basic auth fails with 401, try digest auth
            if resp.status_code == 401:
                resp = requests.get(
                    url,
                    params=params,
                    auth=HTTPDigestAuth(self.username, self.password),
                    timeout=5,
                )

            resp.raise_for_status()
            return resp

        except requests.RequestException as exc:
            logger.warning(f"VAPIX request failed: {exc}")
            return None

    def _ptz_request(self, params: Dict[str, Any]):
        """Make a PTZ API request."""
        # PTZ endpoint expects camera=1, html=no
        merged = {"camera": 1, "html": "no"}
        merged.update(params)

        try:
            resp = requests.get(
                self.ptz_url,
                params=merged,
                auth=(self.username, self.password),
                timeout=5,
            )

            if resp.status_code == 401:
                resp = requests.get(
                    self.ptz_url,
                    params=merged,
                    auth=HTTPDigestAuth(self.username, self.password),
                    timeout=5,
                )

            resp.raise_for_status()
            return resp

        except requests.RequestException as exc:
            logger.warning(f"VAPIX PTZ request failed: {exc}")
            return None


class NoOpSettingsController(SettingsController):
    """No-op controller for cameras with fixed settings."""

    def set_dark_mode(self, exposure: int) -> bool:
        logger.debug("NoOp settings controller: dark mode requested (no action)")
        return True

    def set_bright_mode(self) -> bool:
        logger.debug("NoOp settings controller: bright mode requested (no action)")
        return True

    def capture_defaults(self) -> bool:
        logger.debug("NoOp settings controller: capture defaults (no action)")
        return True
