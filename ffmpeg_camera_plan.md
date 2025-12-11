# FFmpeg Camera Capture Refactor Plan

Replace OpenCV-based camera capture with FFmpeg subprocess for more reliable USB camera handling. Device selection changes from integer indices to device names.

## Design Decisions
- **Exposure control**: Hybrid approach - use OpenCV briefly for camera settings, FFmpeg for capture
- **Device selection**: Names only (breaking change) - no backward compatibility for indices
- **Resolution/FPS**: Hardcoded defaults (1280x720@30fps)

---

## New Module Structure

```
marimapper/
    camera/                      # New package (replaces camera.py)
        __init__.py              # Exports: Camera, list_available_cameras
        camera.py                # Main Camera class (unchanged interface)
        device_listing.py        # Platform-specific device enumeration
        exposure_control.py      # Camera settings via OpenCV (briefly)
        ffmpeg_capture.py        # FFmpeg subprocess frame capture
```

---

## Files to Create

### 1. `marimapper/camera/device_listing.py`
Lists available cameras by NAME on each platform.

```python
def list_available_cameras() -> list[dict]:
    """Returns list of cameras with 'name' and 'identifier' keys."""

def get_ffmpeg_device_string(camera_name: str) -> str:
    """Returns platform-specific FFmpeg input string for device."""
```

**Platform methods:**
- Windows: Parse `ffmpeg -list_devices true -f dshow -i dummy`
- Linux: Parse `v4l2-ctl --list-devices` or `/dev/video*`
- macOS: Parse `ffmpeg -f avfoundation -list_devices true -i ""`

### 2. `marimapper/camera/ffmpeg_capture.py`
Frame capture via FFmpeg subprocess.

```python
class FFmpegCapture:
    def __init__(self, device_name: str):
        """Initialize with device name (e.g., '22_Cam2')."""

    def start(self) -> None:
        """Start FFmpeg subprocess."""

    def read(self) -> np.ndarray:
        """Read single BGR frame (blocking)."""

    def flush(self, count: int = 30) -> None:
        """Discard frames to clear buffer."""

    def stop(self) -> None:
        """Terminate subprocess and cleanup."""
```

**Key implementation from ffmpeg_runner.py:**
- Build platform-specific FFmpeg command
- Read `width * height * 3` bytes from stdout
- Reshape to numpy array: `np.frombuffer(bytes, np.uint8).reshape((H, W, 3))`
- Monitor stderr in background thread for errors

### 3. `marimapper/camera/exposure_control.py`
Camera settings using OpenCV briefly (settings persist on hardware).

```python
class ExposureController:
    def __init__(self, device_name: str):
        """Initialize with device name."""

    def set_dark_mode(self, exposure: int) -> bool:
        """Set minimal exposure for LED detection."""

    def set_bright_mode(self) -> bool:
        """Reset to normal exposure."""

    def apply_settings(self, autofocus: int, exposure_mode: int,
                       gain: int, exposure: int) -> bool:
        """Apply all settings at once."""
```

**Hybrid approach:**
1. Convert device name to OpenCV index (platform-specific lookup)
2. Open camera briefly with `cv2.VideoCapture(index, CAP_DSHOW)`
3. Apply settings via `cap.set(cv2.CAP_PROP_*)`
4. Release immediately - settings persist on camera hardware
5. FFmpeg can now capture with those settings

### 4. `marimapper/camera/camera.py`
Main Camera class - maintains existing interface.

```python
class Camera:
    def __init__(self, device_name: str = None, axis_config: dict = None):
        """
        Args:
            device_name: Camera name (e.g., "22_Cam2"). Use list_available_cameras().
            axis_config: Dict with 'host', 'username', 'password' for Axis IP camera.
        """

    # Unchanged interface:
    def read(self) -> np.ndarray
    def eat(self, count: int = 30) -> None
    def set_exposure(self, exposure: int) -> bool
    def set_autofocus(self, mode: int, focus: int = 0) -> None
    def set_exposure_mode(self, mode: int) -> None
    def set_gain(self, gain: int) -> None
    def reset(self) -> None
```

**Internal delegation:**
- USB cameras: `FFmpegCapture` for frames, `ExposureController` for settings
- Axis IP cameras: Keep existing OpenCV MJPEG stream approach (unchanged)

### 5. `marimapper/camera/__init__.py`
Clean exports.

```python
from .camera import Camera
from .device_listing import list_available_cameras

__all__ = ["Camera", "list_available_cameras"]
```

---

## Files to Modify

### 1. `marimapper/scripts/arg_tools.py`
Change device arguments from indices to names.

**Before:**
```python
parser.add_argument("--device", type=int, default=0)
parser.add_argument("--devices", type=str)  # "0,1,2"
```

**After:**
```python
parser.add_argument("--device", type=str, default=None,
    help="Camera device name (use --list-cameras to see available)")
parser.add_argument("--devices", type=str,
    help="Comma-separated camera names for multi-camera mode")
parser.add_argument("--list-cameras", action="store_true",
    help="List available cameras and exit")
```

### 2. `marimapper/scripts/scanner_cli.py`
Handle `--list-cameras` and device name resolution.

```python
if args.list_cameras:
    from marimapper.camera import list_available_cameras
    cameras = list_available_cameras()
    for cam in cameras:
        print(f"  {cam['name']}")
    sys.exit(0)
```

### 3. `marimapper/scripts/check_camera_cli.py`
Update to use device names instead of indices.

### 4. Import path updates (minimal changes)
Update imports in these files from `from marimapper.camera import Camera` (unchanged):
- `marimapper/detector_process.py`
- `marimapper/detector_worker_process.py`
- `marimapper/unified_detector.py`

The import path stays the same due to `__init__.py` exports.

---

## Files to Delete

- `marimapper/camera.py` - Replaced by `marimapper/camera/` package

---

## Implementation Order

1. **Create device_listing.py** - Platform-specific camera enumeration
2. **Create ffmpeg_capture.py** - Core FFmpeg frame capture (adapt from ffmpeg_runner.py)
3. **Create exposure_control.py** - Hybrid OpenCV settings controller
4. **Create camera.py** - Main Camera class using new modules
5. **Create __init__.py** - Package exports
6. **Update arg_tools.py** - New CLI arguments
7. **Update scanner_cli.py** - Handle --list-cameras
8. **Update check_camera_cli.py** - Device name support
9. **Delete old camera.py** - After verifying new package works
10. **Test end-to-end** - LED detection with new capture system

---

## Readability Guidelines

### Plain English naming
- `list_available_cameras()` not `enumerate_devices()`
- `set_dark_mode()` not `apply_low_exposure_config()`
- `flush()` not `discard_buffered_frames()`

### Single responsibility
- `device_listing.py` - ONLY lists cameras
- `ffmpeg_capture.py` - ONLY captures frames
- `exposure_control.py` - ONLY controls settings

### Clear abstractions
- Platform-specific code isolated in helper functions
- Main Camera class delegates to focused components
- No mixed concerns (capture + settings in same class)

### Docstrings
- Every public function has a one-line description
- Parameters documented with types and examples
- Platform-specific behavior noted where relevant

---

## Critical Files Reference

| File | Path |
|------|------|
| Current camera | `marimapper/camera.py` |
| FFmpeg reference | `ffmpeg_runner.py` |
| CLI args | `marimapper/scripts/arg_tools.py` |
| Scanner CLI | `marimapper/scripts/scanner_cli.py` |
| Check camera CLI | `marimapper/scripts/check_camera_cli.py` |
| Detector (set_cam_dark) | `marimapper/detector.py` |
