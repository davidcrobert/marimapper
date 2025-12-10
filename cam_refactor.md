# Camera Architecture Refactor Plan

## Goal

Unify single-camera and multi-camera scanning into a single architecture where the **only difference** is the number of detector instances. Whether there is 1 camera or 9, the system should:

1. Use the same `Coordinator` class to control LED state
2. Use the same `Detector` class for each camera
3. Follow the same scan flow and synchronization protocol

## Current Architecture Issues

Currently there are **two completely separate code paths**:

### Single-Camera Mode
- **DetectorProcess** (`detector_process.py`) handles:
  - Camera control
  - LED backend control (turns LEDs on/off)
  - Detection logic (calls `enable_and_find_led()`)
  - False positive check (checks for LED visible when all off)
  - Movement check (re-detects first LED at end)
  - Queue communication

### Multi-Camera Mode
- **CoordinatorProcess** (`coordinator_process.py`) handles:
  - LED backend control only
  - Broadcasts "DETECT_LED" commands to workers
  - Waits for all workers to respond
  - No false positive check
  - No movement check

- **DetectorWorkerProcess** (`detector_worker_process.py`) handles:
  - Camera control only
  - Receives commands from coordinator
  - Detects LEDs when commanded
  - Reports results back

**Problems:**
1. False positive check only exists in single-camera mode
2. Movement check only exists in single-camera mode
3. Duplicated detection logic in both `DetectorProcess` and `DetectorWorkerProcess`
4. Different command/communication protocols
5. GUI integration is split between modes

---

## Proposed Unified Architecture

### Core Principle

**Coordinator controls LED backend. Detectors control cameras and detection.**

Regardless of how many cameras exist (1-9), the flow is identical:

```
Coordinator                     Detector(s)
    │                               │
    ├─── Turn all LEDs off ─────────┤
    │                               │
    ├─── Command: CHECK_DARKNESS ───► All detectors check
    │                               │
    ◄─── All respond: CLEAR ────────┤
    │                               │
    │   (If any sees LED, abort)    │
    │                               │
    ├─── FOR each LED: ─────────────┤
    │     │                         │
    │     ├── Turn LED on ──────────┤
    │     │                         │
    │     ├── Command: DETECT_LED ──► All detectors look
    │     │                         │
    │     ◄── Results returned ─────┤ (each decides independently)
    │     │                         │
    │     ├── Turn LED off ─────────┤
    │     │                         │
    │   (Wait for all to finish)    │
    │                               │
    ├─── After last LED: ───────────┤
    │     │                         │
    │     ├── Re-detect first LED ──► Movement check (optional)
    │     │                         │
    │     ◄── Compare positions ────┤
    │                               │
    └─── SCAN_COMPLETE ─────────────►
```

---

## Implementation Plan

### Phase 1: Create Unified Detector Class

**New file:** `marimapper/unified_detector.py`

A single detector class that:
1. Owns one camera
2. Does NOT control LED backend
3. Responds to commands from coordinator
4. Uses the same detection logic as current single-camera mode
5. Supports mask, threshold, dark/bright mode
6. Provides frame output for GUI

```python
class UnifiedDetector(Process):
    """
    Single camera detector that responds to coordinator commands.
    Used identically for single-camera or multi-camera setups.
    """

    def __init__(
        self,
        camera_id: int,
        view_id: int,
        device: str,
        dark_exposure: int,
        threshold: int,
        command_queue: Queue,      # From coordinator
        result_queue: Queue,       # To coordinator
        output_queues: list,       # To SFM, FileWriter, etc.
        display: bool = True,
        axis_config: dict = None,
        frame_queue: Queue = None,  # For GUI
    ):
        ...

    # Commands this detector responds to:
    # - CHECK_DARKNESS: Verify no LED visible, respond CLEAR or FAIL
    # - DETECT_LED (led_id): Try to detect LED, respond with result
    # - REDETECT_LED (led_id): Re-detect for movement check
    # - SCAN_COMPLETE: Reset to preview mode
    # - SET_MASK, SET_DARK, SET_BRIGHT, SET_THRESHOLD
    # - EXIT
```

**Key detection logic** (from current `detector.py` and `detector_process.py`):

```python
def _detect_led(self, led_id: int) -> DetectionResult:
    """
    Detect a single LED. The LED is already ON (coordinator controls this).
    Uses adaptive timeout like current implementation.
    """
    # Switch to dark mode if needed
    if not self._in_dark_mode:
        set_cam_dark(self.cam, self.dark_exposure)
        self.cam.eat()
        self._in_dark_mode = True

    # Wait for stabilization
    time.sleep(0.03)

    # Poll for detection with adaptive timeout
    start_time = time.time()
    deadline = start_time + self.timeout_controller.timeout

    while time.time() < deadline:
        point = find_led(
            self.cam,
            self.threshold,
            self.display,
            self.frame_queue,
            self.mask,
            self.mask_resolution
        )

        if point is not None:
            # Success!
            response_time = time.time() - start_time
            self.timeout_controller.add_response_time(response_time)

            led_2d = LED2D(led_id, self.view_id, point)
            return DetectionResult(success=True, led_2d=led_2d)

        time.sleep(0.02)  # Brief pause before retry

    # Timeout - no detection
    return DetectionResult(success=False, led_id=led_id)
```

---

### Phase 2: Create Unified Coordinator Class

**New file:** `marimapper/unified_coordinator.py`

A coordinator class that:
1. Controls LED backend (turns LEDs on/off)
2. Manages N detectors (where N >= 1)
3. Implements the full scan protocol including:
   - Initial darkness check (false positive prevention)
   - LED-by-LED synchronized detection
   - Movement check at end (optional)
4. Sends results to output queues (SFM, FileWriter, GUI)

```python
class UnifiedCoordinator(Process):
    """
    Coordinates LED scanning across one or more camera detectors.
    """

    def __init__(
        self,
        backend_factory: partial,
        num_detectors: int,
        led_start: int,
        led_end: int,
        check_movement: bool = True,
        detection_timeout: float = 1.5,
        led_stabilization_delay: float = 0.05,
    ):
        ...

        # Create command/result queues for each detector
        self._detector_command_queues: list[Queue] = []
        self._detector_result_queue = Queue()  # Shared by all detectors
```

**Scan protocol implementation:**

```python
def _run_scan(self, led_from: int, led_to: int, view_id: int):
    """Execute full scan with all checks."""

    # 1. DARKNESS CHECK - Verify no false positives
    self._blacken_backend()

    # Broadcast CHECK_DARKNESS to all detectors
    for cmd_q in self._detector_command_queues:
        cmd_q.put(("CHECK_DARKNESS",))

    # Wait for all responses
    responses = self._wait_for_all_responses(timeout=2.0)

    for camera_id, response in responses.items():
        if response != "CLEAR":
            # A camera sees an LED when it shouldn't
            logger.error(f"Camera {camera_id} can see an LED when all should be off")
            self._signal_scan_failed()
            return False

    # 2. DETECTION LOOP
    first_led_positions = {}  # For movement check

    for led_id in range(led_from, led_to):
        if self._cancel_event.is_set():
            logger.info(f"Scan cancelled at LED {led_id}")
            return False

        # Turn LED on
        self.backend.set_led(led_id, True)

        # Wait for LED to stabilize
        time.sleep(self.led_stabilization_delay)

        # Broadcast DETECT_LED to all detectors
        for cmd_q in self._detector_command_queues:
            cmd_q.put(("DETECT_LED", led_id))

        # Wait for all responses
        results = self._wait_for_all_responses(timeout=self.detection_timeout)

        # Turn LED off
        self.backend.set_led(led_id, False)

        # Store first LED positions for movement check
        if led_id == led_from:
            first_led_positions = {
                cam_id: result.position
                for cam_id, result in results.items()
                if result.success
            }

        # Log results
        successful = sum(1 for r in results.values() if r.success)
        logger.debug(f"LED {led_id}: {successful}/{self.num_detectors} cameras detected")

    # 3. MOVEMENT CHECK (if enabled and we detected the first LED)
    if self.check_movement and first_led_positions:
        movement_detected = self._check_movement(led_from, first_led_positions)
        if movement_detected:
            logger.error("Camera movement detected during scan")
            self._signal_scan_deleted(view_id)
            return False

    # 4. SUCCESS
    self._signal_scan_complete(view_id)
    return True

def _check_movement(self, first_led_id: int, original_positions: dict) -> bool:
    """Re-detect first LED and compare positions."""

    # Turn LED on
    self.backend.set_led(first_led_id, True)
    time.sleep(self.led_stabilization_delay)

    # Broadcast REDETECT_LED
    for cmd_q in self._detector_command_queues:
        cmd_q.put(("REDETECT_LED", first_led_id))

    # Wait for responses
    new_results = self._wait_for_all_responses(timeout=self.detection_timeout)

    # Turn LED off
    self.backend.set_led(first_led_id, False)

    # Compare positions
    for camera_id, original_pos in original_positions.items():
        if camera_id not in new_results or not new_results[camera_id].success:
            logger.warning(f"Camera {camera_id}: Could not re-detect LED for movement check")
            continue

        new_pos = new_results[camera_id].position
        distance = get_distance_2d(original_pos, new_pos)

        if distance > 0.01:  # 1% movement threshold
            logger.error(f"Camera {camera_id}: Movement of {int(distance * 100)}% detected")
            return True

    return False
```

---

### Phase 3: Update Scanner to Use Unified Classes

**Modify:** `marimapper/scanner.py`

Remove the dual code paths. Always create:
1. One `UnifiedCoordinator`
2. N `UnifiedDetector` instances (where N = number of cameras)

```python
class Scanner:
    def __init__(
        self,
        output_dir: Path,
        device: str,
        exposure: int,
        threshold: int,
        backend_factory: partial,
        led_start: int,
        led_end: int,
        ...
        axis_config: Optional[dict] = None,     # Single camera
        axis_configs: Optional[List[dict]] = None,  # Multiple cameras
        frame_queue=None,
    ):
        ...

        # Determine camera configurations
        if axis_configs is not None and len(axis_configs) > 0:
            self.camera_configs = axis_configs
        elif axis_config is not None:
            self.camera_configs = [axis_config]
        else:
            # USB camera (single)
            self.camera_configs = [{"device": device}]

        self.num_cameras = len(self.camera_configs)

        # Create coordinator
        self.coordinator = UnifiedCoordinator(
            backend_factory=backend_factory,
            num_detectors=self.num_cameras,
            led_start=led_start,
            led_end=led_end,
            check_movement=check_movement,
        )

        # Create detectors (one per camera)
        self.detectors = []
        self.frame_queues = []  # For GUI

        for camera_id, cam_config in enumerate(self.camera_configs):
            view_id = self.current_view + camera_id

            # Create frame queue for GUI
            cam_frame_queue = Queue(maxsize=3) if frame_queue is not None else None
            self.frame_queues.append(cam_frame_queue)

            detector = UnifiedDetector(
                camera_id=camera_id,
                view_id=view_id,
                device=cam_config.get("device", device),
                dark_exposure=exposure,
                threshold=threshold,
                command_queue=self.coordinator.get_command_queue(camera_id),
                result_queue=self.coordinator.get_result_queue(),
                output_queues=[
                    self.sfm.get_input_queue(),
                    self.detector_update_queue,
                    self.file_writer.get_2d_input_queue(),
                ],
                display=True,
                axis_config=cam_config if "host" in cam_config else None,
                frame_queue=cam_frame_queue,
            )

            self.detectors.append(detector)

        # Connect SFM info output back for LED colorization
        # (Goes to coordinator which can relay to detectors if needed)
        self.sfm.add_output_info_queue(self.coordinator.get_led_info_queue())

        # Start processes
        self.sfm.start()
        self.renderer3d.start()
        self.file_writer.start()
        self.coordinator.start()
        for detector in self.detectors:
            detector.start()
```

---

### Phase 4: Update GUI Integration

**Modify:** `marimapper/gui/main_window.py`

Since the architecture is now unified, the GUI code simplifies:

```python
@pyqtSlot(int, int)
def start_scan(self, led_from: int, led_to: int):
    """Start a scan with the specified LED range."""
    if self.scanner is None:
        return

    # Always use coordinator to start scan
    self.scanner.coordinator.start_scan(led_from, led_to, self.current_view_id)
    self.statusBar().showMessage(f"Scanning LEDs {led_from}-{led_to}...")
```

For camera commands (threshold, dark/bright mode), broadcast to all detectors:

```python
@pyqtSlot(int)
def set_threshold(self, value: int):
    """Set detection threshold for all cameras."""
    for i in range(self.scanner.num_cameras):
        cmd_queue = self.scanner.coordinator.get_command_queue(i)
        cmd_queue.put(("SET_THRESHOLD", value))
```

---

### Phase 5: Remove Deprecated Code

Once the unified system is working, remove:

1. `marimapper/detector_process.py` - Replaced by UnifiedDetector
2. `marimapper/detector_worker_process.py` - Replaced by UnifiedDetector
3. `marimapper/coordinator_process.py` - Replaced by UnifiedCoordinator
4. Dual-mode logic in `scanner.py` (`self.multi_camera_mode`, `_init_single_camera`, `_init_multi_camera`)
5. Dual-mode logic in `main_window.py`

---

## Command Protocol

### Coordinator → Detector Commands

| Command | Parameters | Description |
|---------|------------|-------------|
| `CHECK_DARKNESS` | None | Check if camera sees any LED (false positive check) |
| `DETECT_LED` | `led_id: int` | Detect the specified LED (already turned on by coordinator) |
| `REDETECT_LED` | `led_id: int` | Re-detect LED for movement check |
| `SCAN_COMPLETE` | `view_id: int` | Scan finished, return to preview mode |
| `SET_MASK` | `{mask, resolution}` | Update detection mask |
| `SET_DARK` | None | Set camera to dark exposure mode |
| `SET_BRIGHT` | None | Set camera to bright/preview mode |
| `SET_THRESHOLD` | `value: int` | Update detection threshold |
| `EXIT` | None | Shut down detector process |

### Detector → Coordinator Responses

| Response | Parameters | Description |
|----------|------------|-------------|
| `DARKNESS_CLEAR` | None | No LED visible (darkness check passed) |
| `DARKNESS_FAIL` | None | LED visible when shouldn't be |
| `DETECT_SUCCESS` | `led_id, x, y` | LED detected at position |
| `DETECT_FAIL` | `led_id` | LED not detected within timeout |
| `REDETECT_SUCCESS` | `led_id, x, y` | Movement check detection succeeded |
| `REDETECT_FAIL` | `led_id` | Movement check detection failed |
| `ERROR` | `message` | Error occurred |

---

## Migration Strategy

### Step 1: Implement New Classes (Non-Breaking)
Create `unified_detector.py` and `unified_coordinator.py` without removing existing code.

### Step 2: Add Feature Flag
Add a flag in Scanner to use the new architecture:
```python
use_unified_architecture = True  # Can toggle for testing
```

### Step 3: Parallel Testing
Test both paths to ensure the new architecture behaves identically to the old.

### Step 4: Remove Old Code
Once validated, remove the deprecated classes and dual-mode logic.

---

## Key Implementation Details

### Timeout Controller
The `TimeoutController` class should be shared or identically implemented in both coordinator and detectors. Currently it's in `timeout_controller.py` and used by both `DetectorProcess` and `DetectorWorkerProcess`.

### Frame Queue Handling
Each detector needs its own frame queue for GUI. The GUI's `StatusMonitorThread` already handles multiple frame queues via `frame_ready_multi` signal.

### Output Queues
Each detector sends its detections directly to:
- SFM process (Queue2D)
- FileWriter process (Queue2D)
- GUI update queue (Queue2D)

The coordinator doesn't need to relay detection data—detectors send it directly.

### LED Backend Control
Only the coordinator touches the LED backend. Detectors only observe.

### Cancellation
The coordinator should have a cancel event. On cancellation:
1. Stop LED iteration
2. Turn off current LED
3. Broadcast `SCAN_CANCELLED` to all detectors
4. Emit `FAIL` to output queues

---

## Testing Checklist

- [ ] Single camera scan works identically to old `DetectorProcess`
- [ ] Multi-camera scan works identically to old `CoordinatorProcess` + `DetectorWorkerProcess`
- [ ] False positive check triggers abort when LED visible
- [ ] Movement check detects camera movement
- [ ] Adaptive timeout adjusts based on response times
- [ ] GUI frame display works for all cameras
- [ ] Camera commands (threshold, dark/bright, mask) work for all cameras
- [ ] Scan cancellation works
- [ ] LED colorization from SFM works
- [ ] All output files generated correctly (scan_N.csv, led_map_3d.csv)

---

## File Summary

### New Files
- `marimapper/unified_detector.py` - Single detector class
- `marimapper/unified_coordinator.py` - Single coordinator class

### Modified Files
- `marimapper/scanner.py` - Use unified classes, remove dual-mode logic
- `marimapper/gui/main_window.py` - Simplify to use unified API
- `marimapper/gui/worker.py` - May need minor adjustments

### Deprecated Files (to remove after migration)
- `marimapper/detector_process.py`
- `marimapper/detector_worker_process.py`
- `marimapper/coordinator_process.py`

---

## Plan: Extend Multi-Cam to Webcams (USB)

Goal: allow multi-camera scanning with USB webcams in addition to AXIS IP cameras, reusing the unified coordinator/detector architecture.

1) **Config & CLI wiring**
- Add multi-device parsing to CLI/GUI: accept `--devices "0,1,2"` or mixed configs (USB + AXIS). Serialize per-camera entries into `axis_configs`-style lists (with a `device` key for USB).
- Update `scanner_args_serializer` and project save/load to persist the per-camera device list.

2) **Camera abstraction hardening**
- Ensure `marimapper.camera.Camera` cleanly supports a `device`-only config in multi-cam (no `host`). Validate the unified detector passes device IDs through when axis_config is absent.
- Add explicit resolution/FPS overrides per camera to avoid driver defaults diverging between webcams.

3) **Coordinator/detector plumbing**
- Keep using `UnifiedCoordinator` + `UnifiedDetector`; no protocol changes. Confirm command queues remain per-detector and that `frame_queue` creation works with USB sources.
- Ensure dark/bright exposure setters degrade gracefully for webcams (if iris/auto-exposure controls are unavailable, log-and-continue without blocking refresh).

4) **GUI UX**
- Allow selecting between “AXIS hosts” and “USB devices” in the GUI start dialog; show detected OS camera indices to reduce guesswork.
- Maintain the multi-camera grid; label tiles with the source (`USB 0`, `USB 1`, `AXIS 192.168.x.x`).

5) **Diagnostics & safeguards**
- Add a pre-flight check that all requested devices/hosts are reachable and unique; fail fast with actionable errors.
- Log per-camera backend type so issues (driver vs network) are easy to separate.

6) **Testing matrix**
- 2–3 USB webcams; mixed USB + AXIS; all USB dark/bright toggling; scan progress and masks; darkness check behavior when exposure control is limited.
- Validate output parity (scan CSVs, 3D map) between AXIS-only and USB/mixed setups.
