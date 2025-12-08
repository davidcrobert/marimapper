# Multi-Camera Implementation Plan for MariMapper

## Executive Summary

This document provides a detailed implementation plan for adding simultaneous multi-camera support to MariMapper. The goal is to allow multiple AXIS cameras to scan LEDs in parallel, with synchronized detection and agreement on when to move to the next LED. Each camera provides a separate view for 3D reconstruction.

## Current Architecture Analysis

### Existing System Flow

1. **DetectorProcess** (detector_process.py)
   - Controls both camera capture AND LED backend
   - Captures images from ONE camera
   - Turns LEDs on/off one at a time
   - Detects LED positions in 2D space
   - Sends detections to Queue2D → SFM Process

2. **SFM Process** (sfm_process.py)
   - Receives 2D detections from Queue2D (with view_id)
   - Reconstructs 3D positions using COLMAP
   - Doesn't care if views are sequential or simultaneous

3. **Scanner** (scanner.py)
   - Creates single DetectorProcess
   - User moves camera manually between views
   - Sequential: scan all LEDs from view 1, then view 2, etc.

### Key Insight

The SFM process already supports multiple views - it just receives LED2D detections with different view_ids. The **only** architectural change needed is to make detection **simultaneous** instead of sequential, with proper synchronization.

## Proposed Architecture

### Multi-Camera Mode Overview

```
                    CoordinatorProcess
                           |
      +--------------------+--------------------+
      |                                         |
 LED Backend Control                    Synchronization
      |                                         |
      v                                         v
  Turn LED N ON                    Broadcast "Detect LED N"
      |                                         |
      +----------+------------------+-----------+
                 |                  |
         DetectorWorker1    DetectorWorker2
         (Camera 1)         (Camera 2)
                 |                  |
         Capture & Detect    Capture & Detect
                 |                  |
         Report Success      Report Success
                 |                  |
         Send to Queue2D     Send to Queue2D
                 |                  |
                 +--------+---------+
                          |
                     SFM Process
                   (existing, unchanged)
```

### Core Design Principles

1. **Separation of Concerns**: Coordinator controls LED backend, DetectorWorkers only handle camera capture/detection
2. **Backwards Compatibility**: Single-camera mode continues to work with existing code path
3. **Synchronization First**: All cameras must report before moving to next LED (with timeout)
4. **Independent Views**: Each camera provides a complete, independent view for SFM
5. **Graceful Degradation**: System continues if one camera fails, with warnings

## Detailed Component Design

### 1. CoordinatorProcess (NEW)

**File**: `marimapper/coordinator_process.py`

**Responsibilities**:
- Control LED backend (turn LEDs on/off)
- Coordinate detection across multiple cameras
- Implement synchronization protocol
- Handle timeouts and failures
- Signal scan completion

**Key Methods**:
```python
class CoordinatorProcess(Process):
    def __init__(
        self,
        backend_factory: partial,
        num_cameras: int,
        led_start: int,
        led_end: int,
        detection_timeout: float = 1.25
    )

    def run(self):
        # Main coordination loop
        for led_id in range(led_start, led_end):
            self.detect_led_synchronized(led_id)

    def detect_led_synchronized(self, led_id: int):
        # 1. Turn on LED
        # 2. Broadcast DETECT_LED message to all workers
        # 3. Wait for all workers to respond (with timeout)
        # 4. Collect results
        # 5. Turn off LED
        # 6. Handle failures if needed
```

**Communication Queues**:
- `command_queues`: dict[camera_id, Queue] - Send commands to each DetectorWorker
- `result_queue`: Queue - Shared queue, workers send results with camera_id
- `led_count_queue`: Queue - For returning LED count to Scanner

**Message Protocol**:

*Coordinator → Workers*:
- `('DETECT_LED', led_id)` - Detect this LED (LED will be/is turning on)
- `('SCAN_COMPLETE',)` - Scan finished, shut down gracefully

*Workers → Coordinator*:
- `('RESULT', camera_id, led_id, success, x, y)` - Detection result
- `('ERROR', camera_id, error_msg)` - Worker encountered error

**Synchronization Algorithm**:
```python
def detect_led_synchronized(self, led_id: int):
    # Turn on LED
    self.backend.set_led(led_id, True)
    time.sleep(0.05)  # Brief stabilization delay

    # Broadcast to all workers
    for camera_id, cmd_queue in self.command_queues.items():
        cmd_queue.put(('DETECT_LED', led_id))

    # Wait for all responses
    results = {}
    timeout_time = time.time() + self.detection_timeout

    while len(results) < self.num_cameras:
        remaining_time = timeout_time - time.time()
        if remaining_time <= 0:
            # Timeout - log which cameras didn't respond
            missing = set(self.camera_ids) - set(results.keys())
            logger.warning(f"LED {led_id}: Timeout waiting for cameras {missing}")
            break

        try:
            msg = self.result_queue.get(timeout=min(0.1, remaining_time))
            msg_type, camera_id = msg[0], msg[1]

            if msg_type == 'RESULT':
                _, _, led_id_recv, success, x, y = msg
                results[camera_id] = (success, x, y)

        except queue.Empty:
            continue

    # Turn off LED
    self.backend.set_led(led_id, False)

    # Log results
    successful = sum(1 for success, _, _ in results.values() if success)
    logger.info(f"LED {led_id}: {successful}/{self.num_cameras} cameras detected")
```

**Timeout Handling**:
- Default timeout: 5 seconds per LED
- If timeout occurs, log warning but continue scan
- Track per-camera failure rates
- If camera consistently fails (>80% failure rate), issue warning

### 2. DetectorWorkerProcess (NEW)

**File**: `marimapper/detector_worker_process.py`

**Responsibilities**:
- Capture images from assigned camera
- Detect LED positions when commanded
- Report results to coordinator
- Send successful detections to Queue2D for SFM

**Key Differences from DetectorProcess**:
- NO backend control (coordinator handles this)
- Listens for commands instead of scanning autonomously
- Simpler: just capture → detect → report

**Key Methods**:
```python
class DetectorWorkerProcess(Process):
    def __init__(
        self,
        camera_id: int,
        device: str,
        dark_exposure: int,
        threshold: int,
        command_queue: Queue,
        result_queue: Queue,
        output_queues: list[Queue2D],
        display: bool = False,
        axis_config: dict = None
    )

    def run(self):
        # Initialize camera
        cam = Camera(device_id=self.device, axis_config=self.axis_config)
        set_cam_dark(cam, self.dark_exposure)

        # Main loop: wait for commands
        while True:
            msg = self.command_queue.get()

            if msg[0] == 'DETECT_LED':
                self.detect_and_report(msg[1])
            elif msg[0] == 'SCAN_COMPLETE':
                break

    def detect_and_report(self, led_id: int):
        # Brief delay for LED to turn on (coordinator already turned it on)
        time.sleep(0.05)

        # Capture and detect
        led_detection = find_led(self.cam, self.threshold, self.display)

        if led_detection is not None:
            # Success - send to coordinator
            self.result_queue.put((
                'RESULT',
                self.camera_id,
                led_id,
                True,
                led_detection.u(),
                led_detection.v()
            ))

            # Also send to SFM
            led_2d = LED2D(led_id, self.view_id, led_detection)
            for queue in self.output_queues:
                queue.put(DetectionControlEnum.DETECT, led_2d)
        else:
            # Failed detection
            self.result_queue.put((
                'RESULT',
                self.camera_id,
                led_id,
                False,
                None,
                None
            ))

            # Send SKIP to SFM
            for queue in self.output_queues:
                queue.put(DetectionControlEnum.SKIP, led_id)
```

**View ID Assignment**:
- Each camera gets a unique, persistent view_id
- View IDs assigned at initialization: camera 0 → view_id 0, camera 1 → view_id 1, etc.
- This matches existing file output: `scan_0.csv`, `scan_1.csv`, etc.

**Display Mode**:
- For multi-camera, display should default to FALSE
- Displaying multiple camera windows simultaneously is confusing
- GUI implementation (handled by other dev) can handle multi-camera visualization properly

### 3. Modified Scanner Class

**File**: `marimapper/scanner.py`

**Changes**:
- Add `multi_camera_mode` detection based on axis_config
- If single camera: use existing DetectorProcess (backwards compatibility)
- If multiple cameras: use new CoordinatorProcess + DetectorWorkerProcess instances

**Key Modifications**:
```python
class Scanner:
    def __init__(
        self,
        output_dir: Path,
        device: str,  # Only used for single-camera USB mode
        exposure: int,
        threshold: int,
        backend_factory: partial,
        led_start: int,
        led_end: int,
        interpolation_max_fill: int,
        interpolation_max_error: float,
        check_movement: bool,
        camera_model_name: str,
        axis_config: dict = None,  # OLD: single camera config
        axis_configs: list[dict] = None,  # NEW: multi-camera configs
        frame_queue=None,
    ):
        # Detect mode
        if axis_configs is not None and len(axis_configs) > 1:
            self.multi_camera_mode = True
            self._init_multi_camera(axis_configs, ...)
        else:
            self.multi_camera_mode = False
            self._init_single_camera(axis_config, ...)

    def _init_single_camera(self, axis_config, ...):
        # Existing initialization code (unchanged)
        self.detector = DetectorProcess(...)
        # ... rest of existing code

    def _init_multi_camera(self, axis_configs, ...):
        # Create coordinator
        self.coordinator = CoordinatorProcess(
            backend_factory=backend_factory,
            num_cameras=len(axis_configs),
            led_start=led_start,
            led_end=led_end,
        )

        # Create detector workers
        self.detector_workers = []
        for camera_id, axis_cfg in enumerate(axis_configs):
            worker = DetectorWorkerProcess(
                camera_id=camera_id,
                device=None,  # Not used for AXIS
                dark_exposure=exposure,
                threshold=threshold,
                command_queue=self.coordinator.get_command_queue(camera_id),
                result_queue=self.coordinator.get_result_queue(),
                output_queues=[],  # Added later
                display=False,  # No display in multi-cam
                axis_config=axis_cfg,
            )

            # Connect to output queues
            worker.add_output_queue(self.sfm.get_input_queue())
            worker.add_output_queue(self.file_writer.get_2d_input_queue())
            # ... more queues as needed

            self.detector_workers.append(worker)

        # Start all processes
        self.coordinator.start()
        for worker in self.detector_workers:
            worker.start()

        # Get LED count from coordinator (not detector)
        self.led_count = self.coordinator.get_led_count()
```

**Process Lifecycle**:
- Single camera: Same as before (DetectorProcess)
- Multi camera:
  1. Start SFM, Visualizer, FileWriter (same as before)
  2. Start CoordinatorProcess
  3. Start all DetectorWorkerProcesses
  4. Coordinator automatically runs scan when detect() is called
  5. On close(), stop coordinator and all workers

### 4. Queue Modifications

**File**: `marimapper/queues.py`

**New Queue Types** (optional - can use basic Queue):

```python
class CoordinatorCommandQueue(BaseQueue):
    """Commands from coordinator to detector workers"""

    def send_detect(self, led_id: int):
        self._queue.put(('DETECT_LED', led_id))

    def send_complete(self):
        self._queue.put(('SCAN_COMPLETE',))

    def get(self, timeout=None):
        return self._queue.get(timeout=timeout)


class DetectorResultQueue(BaseQueue):
    """Results from detector workers to coordinator"""

    def send_result(self, camera_id: int, led_id: int, success: bool, x: float, y: float):
        self._queue.put(('RESULT', camera_id, led_id, success, x, y))

    def send_error(self, camera_id: int, error_msg: str):
        self._queue.put(('ERROR', camera_id, error_msg))

    def get(self, timeout=None):
        return self._queue.get(timeout=timeout)
```

**Note**: These are optional convenience wrappers. Can also use raw multiprocessing.Queue with tuple messages.

### 5. CLI Argument Changes

**File**: `marimapper/scripts/arg_tools.py`

**Modifications to add_camera_args()**:

```python
def add_camera_args(parser):
    camera_options = parser.add_argument_group("camera options")

    # Existing single-camera args (unchanged)
    camera_options.add_argument("--device", ...)
    camera_options.add_argument("--axis-host", ...)
    camera_options.add_argument("--axis-username", ...)
    camera_options.add_argument("--axis-password", ...)
    camera_options.add_argument("--exposure", ...)
    camera_options.add_argument("--threshold", ...)

    # NEW: Multi-camera support
    camera_options.add_argument(
        "--axis-cameras",
        type=str,
        help="Multi-camera mode: JSON array of camera configs. "
             "Example: '[{\"host\":\"192.168.1.100\",\"user\":\"root\",\"pass\":\"pwd1\"},"
             "{\"host\":\"192.168.1.101\",\"user\":\"root\",\"pass\":\"pwd2\"}]'",
        default=None,
    )

    # Alternative: Simple comma-separated hosts (all same user/pass)
    camera_options.add_argument(
        "--axis-hosts",
        type=str,
        help="Multi-camera mode: Comma-separated list of AXIS camera IPs. "
             "All cameras use same username/password. Example: '192.168.1.100,192.168.1.101'",
        default=None,
    )
```

**Argument Parsing Logic** (in scanner_cli.py):

```python
# Build axis_configs
axis_configs = None

if args.axis_cameras:
    # Full JSON config
    import json
    axis_configs = json.loads(args.axis_cameras)
    # Validate structure
    for cfg in axis_configs:
        if 'host' not in cfg:
            raise Exception("Each camera config must have 'host'")
        # Add defaults
        cfg.setdefault('username', 'root')
        cfg.setdefault('password', '')

elif args.axis_hosts:
    # Simple comma-separated hosts
    hosts = [h.strip() for h in args.axis_hosts.split(',')]
    if not args.axis_password:
        raise Exception("--axis-password required with --axis-hosts")
    axis_configs = [
        {
            'host': host,
            'username': args.axis_username,
            'password': args.axis_password,
        }
        for host in hosts
    ]

elif args.axis_host:
    # Single camera mode (existing)
    if args.axis_password:
        axis_config = {
            'host': args.axis_host,
            'username': args.axis_username,
            'password': args.axis_password,
        }
    else:
        axis_config = None
else:
    # USB camera mode
    axis_config = None

# Create scanner
scanner = Scanner(
    ...,
    axis_config=axis_config,  # Single camera (existing)
    axis_configs=axis_configs,  # Multi camera (new)
)
```

**Example Usage**:

```bash
# Single camera (existing - unchanged)
marimapper custom ./backend.py --axis-host 192.168.1.100 --axis-password pwd

# Multi-camera with simple hosts
marimapper custom ./backend.py --axis-hosts "192.168.1.100,192.168.1.101" --axis-password pwd

# Multi-camera with full JSON
marimapper custom ./backend.py --axis-cameras '[{"host":"192.168.1.100","password":"pwd1"},{"host":"192.168.1.101","password":"pwd2"}]'
```

### 6. File Output

**No changes needed!**

The existing FileWriterProcess already handles multiple views:
- Each camera (DetectorWorkerProcess) sends detections with its unique view_id
- FileWriterProcess writes `scan_{view_id}.csv` for each view
- Camera 0 → `scan_0.csv`, Camera 1 → `scan_1.csv`, etc.

**Simultaneous vs Sequential doesn't affect file format** - both produce the same output structure.

### 7. Movement Check Handling

**Problem**: Current system re-detects first LED at end to check for camera movement. With multiple cameras:
- Each camera is stationary (mounted)
- Movement check less critical
- But what if a camera physically shifts during scan?

**Solution Options**:

A. **Disable by default** in multi-camera mode
   - Cameras are assumed to be mounted and stationary
   - Add `--enable-movement-check` flag to opt-in

B. **Per-camera movement check**
   - Each worker checks its first LED at the end
   - If any camera detects movement, invalidate its view

**Recommendation**: Option A - disable by default, with opt-in flag.

**Implementation**:
```python
# In DetectorWorkerProcess
if self.check_movement and len(self.detections) > 0:
    first_led = self.detections[0]
    # Re-detect first LED (coordinator needs to turn it on)
    # Send movement check request to coordinator...
```

For Phase 1, **skip movement check in multi-camera mode**. Add in Phase 2 if needed.

## Implementation Phases

### Phase 1: Core Multi-Camera Architecture (MVP)

**Goal**: Get basic multi-camera scanning working

**Tasks**:
1. Create `coordinator_process.py` with CoordinatorProcess class
2. Create `detector_worker_process.py` with DetectorWorkerProcess class
3. Modify `scanner.py` to support multi-camera mode
4. Add CLI arguments for `--axis-hosts` (simple mode)
5. Test with 2 AXIS cameras

**Success Criteria**:
- Two cameras can scan simultaneously
- Synchronization works (both detect same LED before moving on)
- Each camera produces separate scan_{view_id}.csv file
- SFM reconstructs 3D from multi-camera views

**Testing**:
- Unit tests for CoordinatorProcess synchronization logic
- Integration test with dummy backend and simulated cameras
- Manual test with 2 real AXIS cameras

### Phase 2: Robustness & Error Handling

**Goal**: Production-ready reliability

**Tasks**:
1. Implement timeout handling and recovery
2. Add per-camera failure tracking and warnings
3. Handle camera disconnection gracefully
4. Add comprehensive logging
5. Implement graceful shutdown for all processes
6. Add movement check support (optional)

**Success Criteria**:
- System continues if one camera fails
- Clear error messages for common issues
- Proper cleanup on Ctrl+C
- No zombie processes

**Testing**:
- Disconnect camera mid-scan
- Kill worker process mid-scan
- Vary network latency between cameras
- Test with 3+ cameras

### Phase 3: Advanced Features

**Goal**: Enhanced functionality

**Tasks**:
1. Add JSON config support (`--axis-cameras`)
2. Support mixed USB + AXIS cameras
3. Add per-camera exposure/threshold settings
4. Implement camera health monitoring
5. Add performance metrics (detection time per camera)
6. Support hot-swapping failed cameras

**Success Criteria**:
- Flexible camera configuration
- Real-time performance monitoring
- Can recover from camera failures without restarting scan

### Phase 4: Optimization & Polish

**Goal**: Performance and UX improvements

**Tasks**:
1. Optimize synchronization timing (reduce wait time)
2. Add progress indicators per camera
3. Implement adaptive timeout (faster cameras don't wait as long)
4. Add camera calibration verification
5. Performance profiling and optimization

**Success Criteria**:
- Multi-camera scan is <10% slower than single camera per LED
- Clear feedback on which cameras are slow
- Smooth operation with 4+ cameras

## Backwards Compatibility

**Critical Requirement**: Existing single-camera workflows must continue to work unchanged.

**Strategy**:
1. **Auto-detection**: If only one camera specified, use existing DetectorProcess code path
2. **No breaking changes**: All existing CLI arguments work as before
3. **Opt-in**: Multi-camera mode only activates with new `--axis-hosts` or `--axis-cameras` args
4. **Separate code paths**: Don't modify DetectorProcess - create new classes instead

**Validation**:
- All existing tests must pass without modification
- Existing example commands in docs must work
- Single-camera performance unchanged

## Testing Strategy

### Unit Tests

**coordinator_process_test.py**:
- Test synchronization with 2, 3, 4 cameras
- Test timeout handling
- Test failure scenarios (camera doesn't respond)
- Test LED backend control timing

**detector_worker_process_test.py**:
- Test command processing
- Test detection and reporting
- Test graceful shutdown

### Integration Tests

**test_multi_camera_scanner.py**:
- Create Scanner with multiple simulated cameras
- Run full scan with dummy backend
- Verify file output correctness
- Verify SFM receives correct data

### Manual Testing Checklist

- [ ] 2 AXIS cameras scanning simple LED strip
- [ ] 3 AXIS cameras scanning complex LED matrix
- [ ] Camera disconnect during scan
- [ ] Network latency simulation
- [ ] Different camera resolutions/settings
- [ ] Verify 3D reconstruction quality vs sequential scanning
- [ ] Long-running scan (1000+ LEDs)
- [ ] Backwards compatibility: single USB camera
- [ ] Backwards compatibility: single AXIS camera

## Performance Considerations

### Theoretical Performance

**Single Camera (Sequential)**:
- Scan N LEDs from M views
- Total time: N × M × (LED_time + overhead)

**Multi-Camera (Parallel)**:
- Scan N LEDs with M cameras simultaneously
- Total time: N × (LED_time + sync_overhead)
- **Speedup**: ~M× (number of cameras)

**In Practice**:
- 2 cameras: ~1.8x faster (some synchronization overhead)
- 3 cameras: ~2.5x faster
- 4 cameras: ~3.2x faster

### Bottlenecks

1. **Network latency**: AXIS cameras over WiFi may be slow
   - Mitigation: Use wired Ethernet
   - Mitigation: Adjust timeout dynamically based on camera response times

2. **LED switching time**: Physical LED response time (1-10ms typical)
   - Mitigation: Add configurable stabilization delay after LED turns on

3. **Synchronization overhead**: Waiting for all cameras
   - Mitigation: Don't wait for known-slow cameras beyond timeout
   - Mitigation: Adaptive timeouts (fast cameras get shorter timeout)

4. **Python GIL**: May limit parallelism
   - Not a major issue since cameras are in separate processes (true parallelism)

### Optimization Opportunities

1. **Pipeline LED switching**: Start turning on next LED while cameras are still processing
2. **Batch communication**: Send multiple LED commands at once
3. **Predictive timeout**: Track per-camera performance and adjust timeouts
4. **Fast-path for successful detections**: Don't wait full timeout if all cameras respond

## Edge Cases & Known Issues

### Edge Case 1: Camera Clock Skew
**Problem**: Cameras may have different system clocks affecting timestamps.
**Impact**: Low - only affects logging, not functionality.
**Mitigation**: Use coordinator timestamp as reference.

### Edge Case 2: Asymmetric Failures
**Problem**: One camera consistently fails while others succeed.
**Impact**: Missing data for one view reduces 3D reconstruction quality.
**Mitigation**: Track per-camera success rate, warn user if <50% success rate.

### Edge Case 3: Network Partitioning
**Problem**: One camera loses network connection temporarily.
**Impact**: Coordinator times out waiting for that camera.
**Mitigation**: Timeout and continue; log warning for manual intervention.

### Edge Case 4: Synchronization Drift
**Problem**: Small timing differences accumulate over long scans.
**Impact**: Minimal - each LED detection is independent.
**Mitigation**: None needed - self-correcting each LED cycle.

### Edge Case 5: Heterogeneous Cameras
**Problem**: Different camera models with different capabilities.
**Impact**: Slower cameras bottleneck the scan.
**Mitigation**: Per-camera timeout; document requirement for similar cameras.

## Migration Guide

### For End Users

**Migrating from single to multi-camera**:

1. Install multiple AXIS cameras at different angles
2. Note IP addresses of each camera
3. Change command from:
   ```bash
   marimapper backend --axis-host 192.168.1.100 --axis-password pwd
   ```
   to:
   ```bash
   marimapper backend --axis-hosts "192.168.1.100,192.168.1.101,192.168.1.102" --axis-password pwd
   ```
4. Run scan - all cameras will scan simultaneously
5. Expect ~N× speedup where N is number of cameras

**No other changes needed** - output files and workflow identical.

### For Developers

**Key Changes**:
- `Scanner.__init__()` now accepts `axis_configs` (list) in addition to `axis_config` (single)
- Multi-camera mode uses `CoordinatorProcess` + `DetectorWorkerProcess` instead of `DetectorProcess`
- Process creation and lifecycle slightly different in multi-camera mode

**Backwards Compatibility**:
- Existing code using single camera continues to work
- `DetectorProcess` unchanged and still used for single-camera mode

## Security Considerations

### Camera Authentication
- Passwords passed as command-line arguments (visible in process list)
- **Recommendation**: Add support for environment variables or config file
- Example: `MARIMAPPER_CAMERA_PASSWORDS` environment variable with JSON array

### Network Security
- AXIS cameras typically use HTTP digest authentication
- Credentials sent over network (use HTTPS if available)
- **Recommendation**: Document requirement for trusted network

### Resource Exhaustion
- Each camera creates a separate process
- Memory usage: ~50-100MB per camera process
- **Recommendation**: Limit to 10 cameras max (validation in CLI)

## Documentation Updates Needed

1. **README.md**: Add multi-camera section with examples
2. **docs/cameras/axis.md**: Document multi-camera setup and usage
3. **docs/architecture.md**: Explain coordinator/worker architecture
4. **docs/performance.md**: Document expected speedups
5. **CLAUDE.md**: Update with coordinator_process.py and detector_worker_process.py descriptions

## Open Questions

1. **GUI Integration**: How should GUI display multiple camera feeds?
   - Deferred to GUI developer
   - Provide frame_queue per camera? Or multiplexed queue with camera_id?

2. **Camera Calibration**: Should multi-camera mode enforce camera calibration?
   - Phase 1: No, rely on COLMAP auto-calibration
   - Phase 2+: Optional pre-calibration for better accuracy

3. **Heterogeneous Backends**: Can we mix different LED backends per camera?
   - Not needed for MVP - all cameras share one backend
   - Future enhancement if requested

4. **Dynamic Camera Addition**: Can cameras be added/removed mid-scan?
   - Phase 1: No - fixed camera set at scan start
   - Phase 3+: Hot-swap support

## Success Metrics

### Functional Metrics
- [ ] Multiple cameras scan simultaneously
- [ ] Synchronization works correctly (all cameras detect same LED)
- [ ] 3D reconstruction quality matches/exceeds sequential scanning
- [ ] All existing tests pass (backwards compatibility)

### Performance Metrics
- [ ] 2-camera scan is >1.5× faster than sequential
- [ ] 3-camera scan is >2× faster than sequential
- [ ] Synchronization overhead <10% of total scan time

### Quality Metrics
- [ ] 3D reconstruction RMSE same as sequential scanning
- [ ] No degradation in detection accuracy
- [ ] Fewer missed LEDs due to multiple viewing angles

## Conclusion

Multi-camera support is a natural extension of MariMapper's architecture. The SFM pipeline already supports multiple views - we're just making them simultaneous instead of sequential.

**Key Architectural Insight**: Separate backend control (CoordinatorProcess) from camera capture (DetectorWorkerProcess). This clean separation makes implementation straightforward and maintains backwards compatibility.

**Implementation Risk**: Low - existing code largely unchanged, new functionality in separate modules.

**Performance Benefit**: High - near-linear speedup with number of cameras (2× with 2 cameras, 3× with 3 cameras).

**Timeline Estimate**:
- Phase 1 (MVP): 3-5 days
- Phase 2 (Robustness): 2-3 days
- Phase 3 (Advanced): 2-3 days
- Phase 4 (Optimization): 1-2 days
- **Total**: 8-13 days for complete implementation

**Recommendation**: Start with Phase 1 to validate architecture and synchronization approach, then iterate based on real-world testing with multiple AXIS cameras.
