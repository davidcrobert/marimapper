# Hybrid Camera Control Implementation Plan

## Summary

Implement support for a third camera type: **Hybrid (Device + VAPIX)** - where video is captured as a video device via FFmpeg, but settings (exposure/iris) are controlled via VAPIX API.

**Key Design**: Use Strategy pattern to separate video capture from settings control, keeping code clean and maintainable.

---

## JSON Configuration Schema

### File Specification
- New CLI arg: `--camera-config <path>`
- Takes path to JSON file defining cameras

### Schema

```json
[
  {
    "name": "USB Camera (normal)",
    "video": { "type": "device", "device": "22_Cam2" },
    "control": { "type": "opencv" }
  },
  {
    "name": "Pure AXIS Camera",
    "video": {
      "type": "axis_stream",
      "host": "192.168.1.100",
      "username": "root",
      "password": "secret"
    },
    "control": {
      "type": "vapix",
      "host": "192.168.1.100",
      "username": "root",
      "password": "secret"
    }
  },
  {
    "name": "Hybrid (device + VAPIX)",
    "video": { "type": "device", "device": "/dev/video0" },
    "control": {
      "type": "vapix",
      "host": "192.168.1.101",
      "username": "root",
      "password": "secret456"
    }
  }
]
```

---

## VAPIX Settings Scope

The VAPIXSettingsController will support all settings from `axis_config_saved.txt`:

**Sensor Parameters** (via param.cgi):
- `ImageSource.I0.Sensor.Brightness` (0-100)
- `ImageSource.I0.Sensor.ColorLevel` (0-100)
- `ImageSource.I0.Sensor.Contrast` (0-100)
- `ImageSource.I0.Sensor.Sharpness` (0-100)
- `ImageSource.I0.Sensor.LocalContrast` (0-100)
- `ImageSource.I0.Sensor.ToneMapping` (0-100)
- `ImageSource.I0.Sensor.WDR` (on/off)
- `ImageSource.I0.Sensor.WhiteBalance` (auto/manual)
- `ImageSource.I0.Sensor.LowLatencyMode` (on/off)
- `ImageSource.I0.DCIris.Position` (0-100, 0=open, 100=closed)

**PTZ Parameters** (via ptz.cgi):
- `zoom` (0-9999)

The controller will:
1. Save current settings on init (`capture_defaults()`)
2. For dark mode: close iris (position=100)
3. For bright mode: restore saved settings

---

## Architecture Changes

### New Files

| File | Purpose |
|------|---------|
| `marimapper/camera/settings_controller.py` | Abstract base + strategies (OpenCV, VAPIX, NoOp) |
| `marimapper/camera/video_source.py` | Abstract base + implementations (FFmpeg, MJPEG) |
| `marimapper/camera/camera_config.py` | JSON parsing, CameraConfig dataclass, legacy conversion |

### Modified Files

| File | Changes |
|------|---------|
| `marimapper/camera/camera.py` | Refactor to use composition with VideoSource + SettingsController |
| `marimapper/scripts/arg_tools.py` | Add `--camera-config` argument |
| `marimapper/scripts/scanner_cli.py` | Parse JSON config file, pass to Scanner |
| `marimapper/scripts/gui_cli.py` | Same config parsing as scanner_cli |
| `marimapper/scanner.py` | Accept CameraConfig list |
| `marimapper/unified_detector.py` | Use CameraConfig instead of device/axis_config |

---

## Implementation Details

### 1. SettingsController (Strategy Pattern)

```
SettingsController (ABC)
  |-- set_dark_mode(exposure) -> bool
  |-- set_bright_mode() -> bool
  |-- capture_defaults() -> bool

OpenCVSettingsController  # Wraps existing ExposureController
VAPIXSettingsController   # Extracts VAPIX logic from Camera
NoOpSettingsController    # For cameras with fixed settings
```

### 2. VideoSource (Strategy Pattern)

```
VideoSource (ABC)
  |-- start() -> None
  |-- read() -> np.ndarray
  |-- flush(count) -> None
  |-- stop() -> None

FFmpegVideoSource   # Wraps existing FFmpegCapture
MJPEGVideoSource    # Wraps cv2.VideoCapture(mjpeg_url)
```

### 3. Refactored Camera Class

```python
class Camera:
    def __init__(self, video_source: VideoSource, settings_controller: SettingsController, name: str):
        self._video = video_source
        self._settings = settings_controller
        self.name = name

    @classmethod
    def from_legacy_config(cls, device_name=None, axis_config=None) -> "Camera":
        # Backwards compatibility - converts old args to new architecture

    @classmethod
    def from_config(cls, config: CameraConfig) -> "Camera":
        # New path - uses parsed JSON config
```

### 4. CameraConfig Dataclass

```python
@dataclass
class CameraConfig:
    name: str
    video_source: VideoSource
    settings_controller: SettingsController
```

---

## Backwards Compatibility

All existing CLI args continue to work unchanged:
- `--device` / `--devices` -> USB cameras with OpenCV control
- `--axis-host` / `--axis-hosts` -> Pure AXIS with VAPIX control
- `--axis-cameras-json` / `--camera-configs-json` -> Existing JSON formats

Legacy configs get converted via `convert_legacy_config()` to the new `CameraConfig` type internally.

---

## Implementation Sequence

### Phase 1: Core Abstractions (no breaking changes)
1. Create `settings_controller.py` with `SettingsController` ABC and all three implementations
2. Create `video_source.py` with `VideoSource` ABC and both implementations
3. Create `camera_config.py` with JSON parsing and `CameraConfig` dataclass

### Phase 2: Refactor Camera Class
4. Refactor `camera.py` to use composition (VideoSource + SettingsController)
5. Add `from_legacy_config()` class method for backwards compatibility
6. Add `from_config()` class method for new JSON configs

### Phase 3: CLI Integration
7. Add `--camera-config` to `arg_tools.py`
8. Update `scanner_cli.py` to parse config file when provided
9. Update `gui_cli.py` similarly

### Phase 4: Scanner Integration
10. Update `Scanner.__init__()` to accept `camera_configs: List[CameraConfig]`
11. Update `UnifiedDetector` to accept `CameraConfig` instead of `device`/`axis_config`

### Phase 5: Testing
12. Manual testing of all three camera types
13. Test multi-camera with mixed types

---

## Critical Files

- `marimapper/camera/camera.py` - Main refactor target
- `marimapper/camera/exposure_control.py` - Existing OpenCV logic to wrap (read-only)
- `marimapper/scripts/arg_tools.py` - Add new CLI argument
- `marimapper/scripts/scanner_cli.py` - Config file parsing
- `marimapper/scanner.py` - Accept new config type
- `marimapper/unified_detector.py` - Use new config type
