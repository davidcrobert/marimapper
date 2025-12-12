"""
Unified configuration for MariMapper.

Centralizes camera, backend, and scanner configuration that was previously
scattered across arg_tools.py, scanner_args_serializer.py, and camera_config.py.

Provides conversion from:
- Argparse Namespace objects (CLI)
- JSON dictionaries (GUI and config files)
- Legacy camera config formats
"""
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional
import json
import logging

logger = logging.getLogger(__name__)


@dataclass
class CameraVideoConfig:
    """Configuration for camera video source."""
    type: str  # "device", "axis_stream"
    device: Optional[str] = None  # USB device identifier
    host: Optional[str] = None  # Network camera host
    username: str = "root"
    password: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class CameraControlConfig:
    """Configuration for camera settings control."""
    type: str  # "opencv", "vapix", "none"
    host: Optional[str] = None  # For VAPIX control
    username: str = "root"
    password: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class CameraConfig:
    """
    Complete camera configuration.

    Combines video source and settings control, replacing the
    camera/camera_config.py CameraConfig with unified format.
    """
    name: str
    video: CameraVideoConfig
    control: CameraControlConfig

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "video": self.video.to_dict(),
            "control": self.control.to_dict()
        }

    @classmethod
    def from_legacy_axis(cls, host: str, username: str = "root", password: str = "") -> "CameraConfig":
        """Create from legacy AXIS camera arguments."""
        return cls(
            name=f"AXIS @ {host}",
            video=CameraVideoConfig(
                type="axis_stream",
                host=host,
                username=username,
                password=password
            ),
            control=CameraControlConfig(
                type="vapix",
                host=host,
                username=username,
                password=password
            )
        )

    @classmethod
    def from_legacy_usb(cls, device: str) -> "CameraConfig":
        """Create from legacy USB device argument."""
        return cls(
            name=f"USB: {device}",
            video=CameraVideoConfig(
                type="device",
                device=device
            ),
            control=CameraControlConfig(
                type="opencv"
            )
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CameraConfig":
        """Parse from dictionary (JSON config file format)."""
        name = data.get("name", "Camera")

        video_data = data.get("video", {})
        video = CameraVideoConfig(**video_data)

        control_data = data.get("control", {})
        control = CameraControlConfig(**control_data)

        return cls(name=name, video=video, control=control)


@dataclass
class BackendConfig:
    """
    LED backend configuration.

    Consolidates backend config from arg_tools.py and scanner_args_serializer.py.
    """
    type: str  # "artnet", "wled", "fadecandy", "pixelblaze", "custom", "dummy"
    args: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "type": self.type,
            "args": self.args
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BackendConfig":
        """Parse from dictionary."""
        return cls(
            type=data.get("type", "dummy"),
            args=data.get("args", {})
        )


@dataclass
class ScannerConfig:
    """
    Scanner/pipeline configuration.

    Consolidates LED range, interpolation, thresholds, and other scanner settings.
    """
    # LED scanning range
    led_start: int = 0
    led_end: int = 10000

    # Detection parameters
    threshold: int = 128
    dark_exposure: int = -10

    # Interpolation parameters
    interpolation_max_fill: int = 5
    interpolation_max_error: float = 0.2

    # Scanner behavior
    check_movement: bool = True
    camera_model: str = "camera_model_radial"

    # Output
    output_dir: Path = field(default_factory=lambda: Path("."))

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        data = asdict(self)
        data["output_dir"] = str(self.output_dir)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScannerConfig":
        """Parse from dictionary."""
        # Convert output_dir string to Path if present
        if "output_dir" in data and isinstance(data["output_dir"], str):
            data = data.copy()
            data["output_dir"] = Path(data["output_dir"])
        return cls(**data)


@dataclass
class MariMapperConfig:
    """
    Complete MariMapper configuration.

    Top-level config that combines cameras, backend, and scanner settings.
    """
    cameras: List[CameraConfig] = field(default_factory=list)
    backend: Optional[BackendConfig] = None
    scanner: ScannerConfig = field(default_factory=ScannerConfig)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "cameras": [cam.to_dict() for cam in self.cameras],
            "backend": self.backend.to_dict() if self.backend else None,
            "scanner": self.scanner.to_dict()
        }

    def to_json(self, path: Path) -> None:
        """Save configuration to JSON file."""
        with open(path, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)
        logger.info(f"Saved configuration to {path}")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MariMapperConfig":
        """Parse from dictionary."""
        cameras = [CameraConfig.from_dict(cam) for cam in data.get("cameras", [])]

        backend_data = data.get("backend")
        backend = BackendConfig.from_dict(backend_data) if backend_data else None

        scanner_data = data.get("scanner", {})
        scanner = ScannerConfig.from_dict(scanner_data)

        return cls(cameras=cameras, backend=backend, scanner=scanner)

    @classmethod
    def from_json(cls, path: Path) -> "MariMapperConfig":
        """Load configuration from JSON file."""
        with open(path, 'r') as f:
            data = json.load(f)
        logger.info(f"Loaded configuration from {path}")
        return cls.from_dict(data)


def config_from_argparse(args) -> MariMapperConfig:
    """
    Convert argparse Namespace to MariMapperConfig.

    Handles legacy CLI arguments from arg_tools.py and converts them
    to the unified config format.

    Args:
        args: argparse.Namespace from CLI parsing

    Returns:
        MariMapperConfig instance
    """
    # Parse camera configuration
    cameras = []

    # Check for multi-camera configs
    if hasattr(args, 'camera_configs_json') and args.camera_configs_json:
        # JSON array of camera configs
        import json
        camera_dicts = json.loads(args.camera_configs_json)
        cameras = [CameraConfig.from_dict(cam) for cam in camera_dicts]

    elif hasattr(args, 'axis_cameras_json') and args.axis_cameras_json:
        # JSON array of AXIS cameras with per-camera credentials
        import json
        axis_configs = json.loads(args.axis_cameras_json)
        cameras = [
            CameraConfig.from_legacy_axis(
                cfg["host"],
                cfg.get("username", "root"),
                cfg.get("password", "")
            )
            for cfg in axis_configs
        ]

    elif hasattr(args, 'axis_hosts') and args.axis_hosts:
        # Comma-separated AXIS hosts with shared credentials
        hosts = args.axis_hosts.split(',')
        username = getattr(args, 'axis_username', 'root')
        password = getattr(args, 'axis_password', '')
        cameras = [
            CameraConfig.from_legacy_axis(host.strip(), username, password)
            for host in hosts
        ]

    elif hasattr(args, 'devices') and args.devices:
        # Comma-separated USB devices
        devices = args.devices.split(',')
        cameras = [CameraConfig.from_legacy_usb(dev.strip()) for dev in devices]

    elif hasattr(args, 'axis_host') and args.axis_host:
        # Single AXIS camera
        cameras = [CameraConfig.from_legacy_axis(
            args.axis_host,
            getattr(args, 'axis_username', 'root'),
            getattr(args, 'axis_password', '')
        )]

    elif hasattr(args, 'device') and args.device:
        # Single USB camera
        cameras = [CameraConfig.from_legacy_usb(args.device)]

    # Parse backend configuration
    backend = None
    if hasattr(args, 'backend'):
        # Collect backend-specific args
        backend_args = {}
        # We'll need to inspect args for backend-specific fields
        # For now, just store the type
        backend = BackendConfig(type=args.backend, args=backend_args)

    # Parse scanner configuration
    scanner = ScannerConfig(
        led_start=getattr(args, 'start', 0),
        led_end=getattr(args, 'end', 10000),
        threshold=getattr(args, 'threshold', 128),
        dark_exposure=getattr(args, 'exposure', -10),
        interpolation_max_fill=getattr(args, 'interpolation_max_fill', 5),
        interpolation_max_error=getattr(args, 'interpolation_max_error', 0.2),
        check_movement=getattr(args, 'disable_movement_check', True),
        camera_model=getattr(args, 'camera_model', 'camera_model_radial'),
        output_dir=Path(getattr(args, 'dir', '.'))
    )

    return MariMapperConfig(cameras=cameras, backend=backend, scanner=scanner)
