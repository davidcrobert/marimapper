# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MariMapper is a Python tool that uses a webcam to map addressable LEDs to 2D and 3D space. It captures LED positions from multiple camera angles and uses Structure from Motion (SfM) to reconstruct 3D coordinates.

**Key technology**: Uses pycolmap for 3D reconstruction, OpenCV for camera control and LED detection, and Open3D for visualization.

## Development Commands

### Testing
```bash
# Run all tests
pytest

# Run specific test file
pytest test/test_camera.py

# Run with coverage
pytest --cov=marimapper --cov-report=html
```

### Code Quality
```bash
# Format code with black
black .

# Lint with flake8
flake8
```

### Installation for Development
```bash
# Install with development dependencies
uv pip install -e ".[develop]"
```

## Architecture

### Multi-Process Pipeline

The system runs as a coordinated multi-process pipeline with the following components:

**Single-Camera Mode** (existing behavior):
1. **DetectorProcess** (marimapper/detector_process.py): Captures images from camera, controls LED backend, and detects LED positions in 2D space
2. **SFM Process** (marimapper/sfm_process.py): Takes 2D LED detections from multiple views and reconstructs 3D positions using pycolmap
3. **VisualiseProcess** (marimapper/visualize_process.py): Displays the reconstructed 3D LED map in an interactive Open3D window
4. **FileWriterProcess** (marimapper/file_writer_process.py): Writes 2D and 3D LED data to CSV files

**Multi-Camera Mode** (new - for simultaneous scanning):
1. **CoordinatorProcess** (marimapper/coordinator_process.py): Controls LED backend and synchronizes detection across multiple cameras
2. **DetectorWorkerProcess** (marimapper/detector_worker_process.py): Multiple instances, each handling one camera. Captures images and detects LEDs when commanded by coordinator
3. **SFM Process**, **VisualiseProcess**, **FileWriterProcess**: Same as single-camera mode

These processes communicate via multiprocessing Queues defined in `marimapper/queues.py`.

**CRITICAL**: The system uses `set_start_method("spawn")` due to an Open3D bug with estimate_normals on Linux. This is set in scanner.py and must be called before creating any processes. See scanner.py:3-25 for detailed explanation.

### Multi-Camera Scanning

**New Feature**: MariMapper now supports simultaneous multi-camera scanning for faster data capture.

**How it works**:
- CoordinatorProcess controls the LED backend (turns LEDs on/off)
- For each LED, coordinator broadcasts "detect" command to all camera workers
- All cameras capture and detect simultaneously
- Coordinator waits for all responses (with timeout) before moving to next LED
- Each camera produces its own view file (scan_0.csv, scan_1.csv, etc.)
- SFM reconstructs 3D from all views as usual

**Performance**: Near-linear speedup (~N× with N cameras, accounting for sync overhead)

**Example Usage**:
```bash
# Single camera (existing - unchanged)
marimapper custom ./backend.py --axis-host 192.168.1.100 --axis-password pwd

# Multi-camera with simple hosts (all same password)
marimapper custom ./backend.py --axis-hosts "192.168.1.100,192.168.1.101" --axis-password pwd

# Multi-camera with per-camera credentials
marimapper custom ./backend.py --axis-cameras-json '[{"host":"192.168.1.100","password":"pwd1"},{"host":"192.168.1.101","password":"pwd2"}]'
```

**Mode Selection**:
- Single camera: Uses DetectorProcess (existing code path)
- Multiple cameras (axis_configs with len > 1): Uses CoordinatorProcess + DetectorWorkerProcess instances
- Backwards compatible: all existing commands work unchanged

### Backend System

All LED backend drivers live in `marimapper/backends/` with a consistent interface:

Each backend must implement:
- `get_led_count() -> int`: Returns number of controllable LEDs
- `set_led(led_index: int, on: bool) -> None`: Controls individual LED on/off

Backends are registered in `marimapper/backends/backend_utils.py` with factory functions and argument parsers.

Supported backends: FadeCandy, FCMega, WLED, PixelBlaze, ArtNet, dummy, custom

### Camera Control

Camera wrapper in `marimapper/camera.py` provides:
- Automatic capture method detection (DSHOW for Windows, V4L2 for Linux)
- Exposure control for dark captures (critical for LED detection)
- Autofocus disable
- Settings backup/restore

**Important**: Exposure control does not work on macOS (see issue #51)

### Detection Algorithm

The detector (marimapper/detector.py) works by:
1. Setting camera to minimal exposure
2. Ensuring all LEDs are off (checks for false positives)
3. Turning on one LED at a time
4. Finding bright spot in image using thresholding
5. Recording 2D position (normalized to 0-1 range)
6. Optional movement check by re-detecting first LED

Detection uses `cv2.threshold()` to isolate bright spots and `cv2.moments()` to find centroids.

### Structure from Motion (SfM)

The SfM pipeline (marimapper/sfm.py):
1. Populates a COLMAP database with 2D LED observations as "keypoints"
2. Treats each LED as a feature point tracked across views
3. Runs `pycolmap.incremental_mapping()` with custom parameters:
   - `ignore_two_view_tracks = False` (allows reconstruction from 2 views)
   - `min_num_matches = 9` (lowered from default 15)
   - `abs_pose_min_num_inliers = 9` (lowered from default 30)
4. Extracts 3D points from COLMAP's binary output
5. Applies interpolation to fill gaps between detected LEDs

**Critical constraint**: pycolmap version must be 3.11.1 due to issues with > 3.12 (see issue #79)

### Data Flow

```
User initiates scan
    ↓
DetectorProcess captures 2D positions → Queue2D → SFM Process
                                                      ↓
                                              Reconstruct 3D → VisualiseProcess (display)
                                                      ↓
                                              Queue3DInfo → DetectorProcess (colorize LEDs)
    ↓
FileWriterProcess saves CSV files
```

### File Output

The scanner writes to the current working directory:
- `scan_{view_id}.csv`: 2D LED positions for each view (led_id, x, y, view_id)
- `led_map_3d.csv`: Final 3D reconstruction (led_id, x, y, z)

## Entry Points

CLI commands defined in pyproject.toml:
- `marimapper`: Main scanner (marimapper/scripts/scanner_cli.py)
- `marimapper_check_camera`: Camera compatibility test
- `marimapper_check_backend`: Backend driver test
- `marimapper_upload_mapping_to_pixelblaze`: Export map to PixelBlaze controller

## Important Constraints

1. **Python version**: 3.9-3.12 only (pycolmap limitation)
2. **pycolmap version**: Must be 3.11.1 exactly
3. **Process start method**: Must use "spawn" before any multiprocessing
4. **Black exclusions**: Do not format `marimapper/pycolmap_tools/` (vendored COLMAP utilities)
5. **Test coverage exclusions**: Backends and scripts are not included in coverage metrics

## Adding a New Backend

1. Create directory in `marimapper/backends/<name>/`
2. Implement `<name>_backend.py` with Backend class (see FadeCandy example)
3. Create factory function: `<name>_backend_factory(argparse_args) -> partial`
4. Create arg setter: `<name>_backend_set_args(parser)` to add CLI arguments
5. Register both in `marimapper/backends/backend_utils.py` dictionaries
6. Add documentation in `docs/backends/<name>.md`

The Backend class only needs `get_led_count()` and `set_led(index, on)` methods. The `set_leds(buffer)` method is optional but enables colorful preview of reconstruction quality.


marimapper custom ./my_backend.py --axis-host 192.170.100.232 --axis-username root --axis-password hemmer
marimapper-gui artnet --axis-host 192.170.90.198 --axis-username root --axis-password hemmer
marimapper artnet --axis-hosts "192.170.90.198,192.170.90.199" --axis-username root --axis-password hemmer
marimapper-gui artnet --axis-hosts "192.170.90.198,192.170.90.199" --axis-password hemmer