"""
Platform-specific camera device enumeration.

Lists available cameras by name on Windows, Linux, and macOS.
"""
import subprocess
import platform
import re
import logging
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


class CameraDevice:
    """Represents a camera device with its name and platform-specific identifier."""

    def __init__(self, name: str, identifier: str, platform_name: str):
        """
        Args:
            name: Human-readable camera name (e.g., "22_Cam2")
            identifier: Platform-specific device identifier for FFmpeg
            platform_name: "Windows", "Linux", or "Darwin"
        """
        self.name = name
        self.identifier = identifier
        self.platform = platform_name

    def to_dict(self) -> dict:
        """Returns dictionary representation."""
        return {
            "name": self.name,
            "identifier": self.identifier,
            "platform": self.platform
        }


def list_available_cameras() -> List[CameraDevice]:
    """
    Lists all available camera devices on the current platform.

    Returns:
        List of CameraDevice objects with name and identifier.
    """
    system = platform.system()

    if system == "Windows":
        return _list_cameras_windows()
    elif system == "Linux":
        return _list_cameras_linux()
    elif system == "Darwin":
        return _list_cameras_macos()
    else:
        logger.error(f"Unsupported platform: {system}")
        return []


def get_ffmpeg_device_string(camera: CameraDevice) -> str:
    """
    Returns the FFmpeg input string for a camera device.

    Args:
        camera: CameraDevice object

    Returns:
        FFmpeg-compatible device string (e.g., "video=22_Cam2" for Windows)
    """
    if camera.platform == "Windows":
        return f"video={camera.identifier}"
    elif camera.platform == "Linux":
        return camera.identifier  # e.g., "/dev/video0"
    elif camera.platform == "Darwin":
        return camera.identifier  # e.g., "0" or device name
    else:
        return camera.identifier


def find_camera_by_name(name: str, cameras: Optional[List[CameraDevice]] = None) -> Optional[CameraDevice]:
    """
    Find a camera by name (case-insensitive, partial match).

    Args:
        name: Camera name to search for
        cameras: Optional list of cameras to search. If None, lists all cameras.

    Returns:
        CameraDevice if found, None otherwise
    """
    if cameras is None:
        cameras = list_available_cameras()

    name_lower = name.lower()

    # Try exact match first
    for cam in cameras:
        if cam.name.lower() == name_lower:
            return cam

    # Try partial match
    for cam in cameras:
        if name_lower in cam.name.lower():
            return cam

    return None


def _list_cameras_windows() -> List[CameraDevice]:
    """
    Lists cameras on Windows using DirectShow.

    Runs: ffmpeg -list_devices true -f dshow -i dummy
    """
    try:
        # Run FFmpeg to list DirectShow devices
        result = subprocess.run(
            ["ffmpeg", "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
            capture_output=True,
            text=True,
            timeout=10
        )

        # FFmpeg outputs device list to stderr
        output = result.stderr

        cameras = []
        # Parse output for video devices
        # Format: [dshow @ ...] "Device Name" (video)
        video_device_pattern = r'\[dshow[^\]]*\]\s+"([^"]+)"\s*(?:\(video\))?'

        in_video_section = False
        for line in output.split('\n'):
            # Look for video devices section
            if "DirectShow video devices" in line:
                in_video_section = True
                continue
            elif "DirectShow audio devices" in line:
                in_video_section = False
                continue

            if in_video_section:
                match = re.search(video_device_pattern, line)
                if match:
                    device_name = match.group(1)
                    cameras.append(CameraDevice(
                        name=device_name,
                        identifier=device_name,
                        platform_name="Windows"
                    ))

        logger.info(f"Found {len(cameras)} Windows camera(s)")
        return cameras

    except FileNotFoundError:
        logger.error("FFmpeg not found. Please install FFmpeg and add to PATH.")
        return []
    except subprocess.TimeoutExpired:
        logger.error("FFmpeg device listing timed out")
        return []
    except Exception as e:
        logger.error(f"Error listing Windows cameras: {e}")
        return []


def _list_cameras_linux() -> List[CameraDevice]:
    """
    Lists cameras on Linux using Video4Linux2.

    First tries v4l2-ctl, falls back to /dev/video* enumeration.
    """
    # Try v4l2-ctl first (provides friendly names)
    try:
        result = subprocess.run(
            ["v4l2-ctl", "--list-devices"],
            capture_output=True,
            text=True,
            timeout=5
        )

        if result.returncode == 0:
            return _parse_v4l2_output(result.stdout)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        logger.debug("v4l2-ctl not available, falling back to /dev/video* enumeration")

    # Fallback: enumerate /dev/video* devices
    cameras = []
    video_devices = sorted(Path("/dev").glob("video*"))

    for device_path in video_devices:
        # Skip non-numeric suffixes (like video0_metadata)
        if not device_path.name[5:].isdigit():
            continue

        cameras.append(CameraDevice(
            name=device_path.name,
            identifier=str(device_path),
            platform_name="Linux"
        ))

    logger.info(f"Found {len(cameras)} Linux camera(s)")
    return cameras


def _parse_v4l2_output(output: str) -> List[CameraDevice]:
    """
    Parse v4l2-ctl --list-devices output.

    Format:
        Camera Name (usb-...):
            /dev/video0
            /dev/video1
    """
    cameras = []
    current_name = None

    for line in output.split('\n'):
        line = line.rstrip()
        if not line:
            continue

        # Check if this is a device name line (not indented)
        if not line.startswith('\t') and not line.startswith(' ' * 4):
            # Extract device name (remove USB path info in parentheses)
            current_name = re.sub(r'\s*\([^)]+\):\s*$', '', line)
        else:
            # This is a device path line (indented)
            device_path = line.strip()
            if device_path.startswith('/dev/video') and current_name:
                # Only include video devices, not metadata devices
                if device_path[-1].isdigit() or not any(char.isalpha() for char in device_path.split('video')[1]):
                    cameras.append(CameraDevice(
                        name=f"{current_name} ({Path(device_path).name})",
                        identifier=device_path,
                        platform_name="Linux"
                    ))

    return cameras


def _list_cameras_macos() -> List[CameraDevice]:
    """
    Lists cameras on macOS using AVFoundation.

    Runs: ffmpeg -f avfoundation -list_devices true -i ""
    """
    try:
        result = subprocess.run(
            ["ffmpeg", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
            capture_output=True,
            text=True,
            timeout=10
        )

        # FFmpeg outputs device list to stderr
        output = result.stderr

        cameras = []
        # Parse output for video devices
        # Format: [AVFoundation indev @ ...] [0] Device Name
        device_pattern = r'\[AVFoundation[^\]]*\]\s*\[(\d+)\]\s+(.+)'

        for line in output.split('\n'):
            match = re.search(device_pattern, line)
            if match:
                device_index = match.group(1)
                device_name = match.group(2).strip()

                cameras.append(CameraDevice(
                    name=device_name,
                    identifier=device_index,
                    platform_name="Darwin"
                ))

        logger.info(f"Found {len(cameras)} macOS camera(s)")
        return cameras

    except FileNotFoundError:
        logger.error("FFmpeg not found. Please install FFmpeg.")
        return []
    except subprocess.TimeoutExpired:
        logger.error("FFmpeg device listing timed out")
        return []
    except Exception as e:
        logger.error(f"Error listing macOS cameras: {e}")
        return []
