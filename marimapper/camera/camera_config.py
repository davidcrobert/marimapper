"""
Parser for JSON camera configuration files.

Converts JSON config into VideoSource and SettingsController instances.
"""
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import logging

from .video_source import VideoSource, FFmpegVideoSource, MJPEGVideoSource
from .settings_controller import (
    SettingsController,
    OpenCVSettingsController,
    VAPIXSettingsController,
    NoOpSettingsController
)
from .device_listing import find_camera_by_name

logger = logging.getLogger(__name__)


@dataclass
class CameraConfig:
    """
    Parsed camera configuration.

    Stores configuration data (not objects) to allow pickling for multiprocessing.
    VideoSource and SettingsController are created lazily when needed.
    """
    name: str
    video_config: Dict[str, Any]  # Configuration for video source
    control_config: Dict[str, Any]  # Configuration for settings controller

    def create_video_source(self) -> VideoSource:
        """Create VideoSource from config (called in subprocess)."""
        return _create_video_source(self.video_config, self.name)

    def create_settings_controller(self) -> SettingsController:
        """Create SettingsController from config (called in subprocess)."""
        return _create_settings_controller(self.control_config, self.video_config, self.name)


def parse_camera_config_file(config_path: Path) -> List[CameraConfig]:
    """
    Parse JSON camera configuration file.

    Args:
        config_path: Path to JSON config file

    Returns:
        List of CameraConfig objects

    Raises:
        FileNotFoundError: If config file doesn't exist
        ValueError: If config is invalid
    """
    if not config_path.exists():
        raise FileNotFoundError(f"Camera config file not found: {config_path}")

    with open(config_path, 'r') as f:
        configs = json.load(f)

    if not isinstance(configs, list):
        raise ValueError("Camera config must be a JSON array")

    return [_parse_single_camera(cfg, i) for i, cfg in enumerate(configs)]


def _parse_single_camera(cfg: Dict[str, Any], index: int) -> CameraConfig:
    """Parse a single camera configuration entry."""
    name = cfg.get("name", f"Camera {index}")

    # Parse video source config
    video_cfg = cfg.get("video")
    if video_cfg is None:
        raise ValueError(f"Camera '{name}' missing 'video' field")
    # Validate it's valid (will raise if invalid)
    _validate_video_config(video_cfg, name)

    # Parse settings controller config
    control_cfg = cfg.get("control")
    if control_cfg is None:
        raise ValueError(f"Camera '{name}' missing 'control' field")
    # Validate it's valid (will raise if invalid)
    _validate_control_config(control_cfg, video_cfg, name)

    return CameraConfig(
        name=name,
        video_config=video_cfg,
        control_config=control_cfg
    )


def _validate_video_config(cfg: Dict[str, Any], camera_name: str) -> None:
    """Validate video source configuration."""
    source_type = cfg.get("type")

    if source_type == "device":
        device = cfg.get("device")
        if not device:
            raise ValueError(f"Camera '{camera_name}': device video source requires 'device' field")
    elif source_type == "axis_stream":
        host = cfg.get("host")
        password = cfg.get("password")
        if not host or not password:
            raise ValueError(
                f"Camera '{camera_name}': axis_stream requires 'host' and 'password' fields"
            )
    else:
        raise ValueError(
            f"Camera '{camera_name}': Unknown video source type '{source_type}'. "
            f"Expected 'device' or 'axis_stream'"
        )


def _validate_control_config(control_cfg: Dict[str, Any], video_cfg: Dict[str, Any], camera_name: str) -> None:
    """Validate settings controller configuration."""
    ctrl_type = control_cfg.get("type")

    if ctrl_type == "opencv":
        if video_cfg.get("type") != "device":
            raise ValueError(
                f"Camera '{camera_name}': opencv control only works with 'device' video source"
            )
    elif ctrl_type == "vapix":
        host = control_cfg.get("host")
        password = control_cfg.get("password")
        if not host or not password:
            raise ValueError(
                f"Camera '{camera_name}': vapix control requires 'host' and 'password' fields"
            )
    elif ctrl_type == "none":
        pass  # No validation needed
    else:
        raise ValueError(
            f"Camera '{camera_name}': Unknown settings control type '{ctrl_type}'. "
            f"Expected 'opencv', 'vapix', or 'none'"
        )


def _create_video_source(cfg: Dict[str, Any], camera_name: str) -> VideoSource:
    """Create VideoSource from config (called in subprocess)."""
    source_type = cfg.get("type")

    if source_type == "device":
        device = cfg.get("device")
        # Try to resolve device name to identifier
        camera_device = find_camera_by_name(device)
        if camera_device is None:
            logger.warning(f"Could not find camera '{device}' in device list, using name as-is")
            device_identifier = device
        else:
            device_identifier = camera_device.identifier
            logger.info(f"Resolved '{device}' to {camera_device.name}")

        # Get resolution from config (defaults to 640x360)
        width = cfg.get("width", 640)
        height = cfg.get("height", 360)

        return FFmpegVideoSource(device_identifier, width=width, height=height)

    elif source_type == "axis_stream":
        host = cfg.get("host")
        username = cfg.get("username", "root")
        password = cfg.get("password")
        return MJPEGVideoSource(host, username, password)

    else:
        raise ValueError(f"Unknown video source type: {source_type}")


def _create_settings_controller(
    control_cfg: Dict[str, Any],
    video_cfg: Dict[str, Any],
    camera_name: str
) -> SettingsController:
    """Create SettingsController from config (called in subprocess)."""
    ctrl_type = control_cfg.get("type")

    if ctrl_type == "opencv":
        device = video_cfg.get("device")
        # Resolve device name to identifier
        camera_device = find_camera_by_name(device)
        if camera_device is None:
            logger.warning(f"Could not find camera '{device}' in device list, using name as-is")
            device_identifier = device
        else:
            device_identifier = camera_device.identifier

        return OpenCVSettingsController(device_identifier)

    elif ctrl_type == "vapix":
        host = control_cfg.get("host")
        username = control_cfg.get("username", "root")
        password = control_cfg.get("password")
        return VAPIXSettingsController(host, username, password)

    elif ctrl_type == "none":
        return NoOpSettingsController()

    else:
        raise ValueError(f"Unknown settings control type: {ctrl_type}")


def convert_legacy_config(legacy_cfg: Dict[str, Any]) -> CameraConfig:
    """
    Convert legacy camera config (axis_config or device dict) to new format.

    This maintains backwards compatibility with existing CLI args.

    Args:
        legacy_cfg: Either {"host": ..., "username": ..., "password": ...}
                    or {"device": ..., "width": ..., "height": ...}

    Returns:
        CameraConfig instance

    Raises:
        ValueError: If config format is invalid
    """
    if "host" in legacy_cfg:
        # Pure AXIS camera (legacy)
        host = legacy_cfg["host"]
        username = legacy_cfg.get("username", "root")
        password = legacy_cfg.get("password", "")

        return CameraConfig(
            name=f"AXIS @ {host}",
            video_config={
                "type": "axis_stream",
                "host": host,
                "username": username,
                "password": password
            },
            control_config={
                "type": "vapix",
                "host": host,
                "username": username,
                "password": password
            }
        )

    elif "device" in legacy_cfg:
        # USB camera (legacy)
        device = legacy_cfg["device"]
        width = legacy_cfg.get("width", 640)
        height = legacy_cfg.get("height", 360)

        return CameraConfig(
            name=f"USB: {device}",
            video_config={
                "type": "device",
                "device": device,
                "width": width,
                "height": height
            },
            control_config={
                "type": "opencv"
            }
        )

    else:
        raise ValueError(f"Invalid legacy config: {legacy_cfg}")
