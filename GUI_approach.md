# MariMapper GUI Implementation Plan

## Executive Summary

MariMapper currently uses a multi-process architecture with OpenCV windows and console I/O. I'll create a modern GUI that maintains this robust architecture while providing an intuitive interface with controls, live displays, and status monitoring.

---

## 1. GUI Framework Recommendation

### **Recommended: PyQt6** (or PySide6 if licensing is a concern)

**Rationale:**
- **Rich widget library**: Built-in support for sliders, tabs, menus, status bars, video display
- **Multi-threaded/process friendly**: Excellent signal/slot system for async communication
- **OpenCV integration**: Easy conversion `cv2` → `QImage` → `QPixmap` for video display
- **Open3D integration options**: Can embed via `QWindow` or run alongside as separate window
- **Cross-platform**: Works on Windows, Linux, macOS (unlike some alternatives)
- **Mature ecosystem**: Qt Designer for rapid prototyping, extensive documentation
- **Customizable styling**: Qt Style Sheets (CSS-like) for modern appearance

**Alternative Options Considered:**

| Framework | Pros | Cons | Verdict |
|-----------|------|------|---------|
| **Tkinter** | Built-in, simple | Limited widgets, dated appearance, poor video performance | ❌ Too basic |
| **Dear PyGui** | GPU-accelerated, modern | Newer/less mature, different paradigm | ⚠️ Risky for complex UI |
| **Kivy** | Mobile-friendly, modern | Overkill for desktop, unusual API | ❌ Not desktop-focused |
| **wxPython** | Native look | Less documentation, smaller community | ⚠️ Secondary choice |

**Final Choice: PyQt6** (or PySide6 for LGPL licensing)

---

## 2. Architecture Design

### **Core Principle: Non-Invasive Wrapper Architecture**

The GUI will **wrap** the existing `Scanner` class rather than replacing it, preserving all CV functionality.

```
┌─────────────────────────────────────────────────────┐
│                   GUI Application                    │
│  (PyQt6 Main Window - runs in main thread)         │
│                                                      │
│  ┌────────────────┐  ┌──────────────────────────┐  │
│  │  Control Panel │  │  Status Monitor Thread   │  │
│  │  - Start/Stop  │  │  - Queue polling         │  │
│  │  - LED range   │  │  - Process health check  │  │
│  │  - Threshold   │  │  - Emits Qt signals      │  │
│  │  - Backend     │  └──────────────────────────┘  │
│  └────────────────┘                                 │
│                                                      │
│  ┌────────────────┐  ┌──────────────────────────┐  │
│  │  Detector View │  │  3D Viewer Control       │  │
│  │  (QLabel)      │  │  (External Open3D        │  │
│  │  - OpenCV feed │  │   window managed)        │  │
│  │  - Overlays    │  └──────────────────────────┘  │
│  └────────────────┘                                 │
│                                                      │
│  ┌─────────────────────────────────────────────┐   │
│  │  Log/Status Output (QTextEdit)              │   │
│  └─────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
                      │
                      │ Owns & controls
                      ▼
         ┌─────────────────────────┐
         │    Scanner Instance     │
         │  (existing scanner.py)  │
         └─────────────────────────┘
                      │
         ┌────────────┴────────────────┐
         │                             │
         ▼                             ▼
  [DetectorProcess]            [SFM Process]
         │                             │
         ▼                             ▼
  [VisualiseProcess]         [FileWriterProcess]
```

**Key Design Decisions:**

1. **Main GUI thread**: PyQt6 event loop (replaces console input)
2. **Scanner runs as is**: No changes to multiprocessing architecture
3. **Status monitoring thread**: Polls queues and emits Qt signals (thread-safe)
4. **Video display**: Intercept frames before `cv2.imshow()` → send to GUI
5. **Open3D window**: Keep as separate process initially (can embed later)

---

## 3. Implementation Phases

### **Phase 1: Foundation & Basic GUI** (Core functionality)

**Goals:**
- Launch GUI window with minimal features
- Replace console I/O with GUI controls
- Display detector video feed in GUI
- Maintain full CV functionality

**Tasks:**
1. Create `marimapper/gui/` module structure:
   ```
   marimapper/gui/
   ├── __init__.py
   ├── main_window.py       # QMainWindow subclass
   ├── widgets/
   │   ├── __init__.py
   │   ├── detector_widget.py    # Video display
   │   ├── control_panel.py      # Start/Stop controls
   │   └── log_widget.py         # Status output
   ├── worker.py            # Scanner worker thread
   └── signals.py           # Custom Qt signals
   ```

2. Modify `detector_process.py`:
   - Add optional `frame_queue` parameter to constructor
   - When present, send frames via queue instead of `cv2.imshow()`
   - Keep `cv2.imshow()` as fallback for CLI mode
   - **Critical**: Test that this doesn't slow down detection

3. Create `gui_scanner.py` entry point:
   - CLI command: `marimapper-gui`
   - Parses same arguments as `scanner_cli.py`
   - Launches PyQt6 application
   - Instantiates `MainWindow` with args

4. Build `MainWindow` (PyQt6):
   - Central widget with video display (640x480 initial size)
   - Sidebar control panel:
     - Start/Stop buttons
     - LED range inputs (From/To)
     - View counter display
   - Bottom log pane (read-only text area)
   - Menu bar: File → Exit, Help → About

5. Implement frame update mechanism:
   - `StatusMonitorThread(QThread)`: Polls `frame_queue` from detector
   - Emits `frame_ready` signal with numpy array
   - Main window slot converts: `cv2` → `QImage` → `QPixmap` → `QLabel`
   - Target: 30 FPS display (queue can drop frames if GUI lags)

6. Replace console input:
   - Start button → calls `scanner.detector.detect(led_from, led_to, view_id)`
   - Instead of `get_user_confirmation()`, GUI controls trigger scans
   - View counter auto-increments on completion

**Testing:**
- Run full scan with GUI vs CLI mode
- Verify identical CSV outputs
- Check for frame drops or detection slowdowns
- Test on Windows and Linux

---

### **Phase 2: Enhanced Controls & Monitoring** (Usability)

**Goals:**
- Add real-time parameter adjustment
- Display reconstruction status
- Improve visual feedback

**Tasks:**
1. Expand control panel:
   - **Exposure slider**: Live adjustment (0-255)
     - Connected to `camera.set_exposure()` via signal
     - Display current value label
   - **Threshold slider**: Detection sensitivity (0-255)
     - Pass to detector, no restart required
   - **Backend selector**: Dropdown with all registered backends
   - **Camera selector**: Dropdown with available devices
   - **Interpolation toggle**: Enable/disable gap filling

2. Add status indicators:
   - **Process health indicators**: Green/red lights for each process
     - Monitor via `scanner.check_for_crash()` every 1s
     - Red light + error message if crash detected
   - **LED detection status table** (QTableWidget):
     - Columns: LED ID | Status | Views | Error
     - Populated from `Queue3DInfo` data
     - Color-coded rows:
       - 🟢 Green: RECONSTRUCTED
       - 🔵 Cyan: INTERPOLATED/MERGED
       - 🟠 Orange: DETECTED (need more views)
       - 🔴 Red: UNRECONSTRUCTABLE
       - ⚪ Blue: NONE

3. Enhanced detector display:
   - Overlay current LED ID on video
   - Show detection count: "LED 47/512 (View 3)"
   - Draw contour and crosshair (from detector.py)
   - FPS counter

4. Log enhancements:
   - Timestamps for each message
   - Color-coded severity (info=black, warning=orange, error=red)
   - Auto-scroll to bottom
   - "Clear Log" button

**Testing:**
- Adjust exposure mid-scan, verify detection continues
- Check status table accuracy against CSV output
- Stress test with 1000+ LED strips

---

### **Phase 3: Multi-View Display & 3D Integration** (Visualization)

**Goals:**
- Show multiple camera views simultaneously
- Integrate 3D viewer with GUI controls
- Display camera poses

**Tasks:**
1. Multi-view display:
   - Replace single detector widget with **tab widget**:
     - Tab 1: "Live Detector" (current view)
     - Tab 2: "View 1" (historical)
     - Tab 3: "View 2" (historical)
     - ...
   - Store captured views in memory (configurable limit, e.g., 10)
   - Each historical view shows:
     - Final frame with all detected LEDs marked
     - Detection count and timestamp

2. 3D viewer integration (two approaches, start with #1):

   **Approach 1: Separate Window with Controls** (easier)
   - Keep Open3D in `VisualiseProcess` (daemon)
   - Add GUI controls to manipulate view:
     - "Reset Camera" button
     - "Toggle Normals" checkbox
     - "Show Frustums" checkbox
     - "Show Strips" checkbox
   - Implement via `Queue3DCommand` → VisualiseProcess
   - VisualiseProcess reads commands, calls Open3D API

   **Approach 2: Embedded Viewer** (future enhancement)
   - Research Open3D → Qt integration (via `QWindow` or `QVTKOpenGLNativeWidget`-style approach)
   - May require custom rendering loop
   - **Risk**: Complex, might break Open3D functionality

3. Camera pose visualization:
   - Add 2D camera pose overlay (bird's-eye view):
     - Small widget (256x256) showing camera positions
     - Colored dots for each view
     - Arrows showing camera orientation
   - Populated from SFM reconstruction data (camera rotation/translation matrices)

**Testing:**
- Verify 3D viewer commands work (Open3D API compatibility)
- Test historical view memory usage with 20+ views
- Check rendering performance with large point clouds

---

### **Phase 4: Advanced Features** (Power User)

**Goals:**
- Batch scanning workflows
- Configuration presets
- Export options

**Tasks:**
1. Batch scan mode:
   - "Multi-View Capture" wizard:
     - Step 1: Set LED range and detection params
     - Step 2: Auto-capture N views with countdown timer
     - Step 3: Review detections before reconstruction
     - Step 4: Export results
   - Optional: Automated camera movement prompts ("Rotate camera 30° clockwise")

2. Configuration presets:
   - Save/Load button for settings:
     - Backend type + args
     - Camera device + exposure
     - LED range + threshold
     - Interpolation parameters
   - Stored as JSON in `~/.marimapper/presets/`
   - Dropdown to select preset

3. Enhanced export options:
   - **File format selector**: CSV (current) | JSON | NPY (numpy)
   - **Coordinate system transformation**:
     - GUI for setting origin/scale
     - Apply transformation before export
   - **Live preview export**: Download snapshot during scan (partial reconstruction)

4. Diagnostics panel (Help → Diagnostics):
   - System info: Python version, pycolmap version, OpenCV version
   - Camera capabilities: Supported controls, resolution, FPS
   - Backend health check: Run `check_backend` test from GUI
   - Process memory usage monitor

**Testing:**
- Batch scan 5 views with countdown, verify smooth operation
- Load preset and verify all settings applied
- Export in all formats, validate data integrity

---

### **Phase 5: Polish & Aesthetics** (User Experience)

**Goals:**
- Modern, attractive appearance
- Responsive design
- User-friendly error handling

**Tasks:**
1. Visual styling (Qt Style Sheets):
   - Choose color scheme: Dark mode + light mode toggle
   - Modern flat design (reference: VS Code, Blender UI)
   - Consistent padding, margins, fonts
   - Icon set for buttons (e.g., Feather Icons or Material Icons)

2. Layout improvements:
   - Responsive splitters: User can resize panes
   - Collapsible panels: Hide controls when not needed
   - Full-screen video mode (F11)
   - Remember window size/position across sessions

3. Improved error handling:
   - **Process crashes**: Show dialog with error details, offer restart
   - **Detection failures**: Highlight problematic LED in table, suggest solutions
   - **Camera connection issues**: Auto-retry with progress bar
   - **Backend errors**: Clear error messages with documentation links

4. User onboarding:
   - First-run wizard:
     - Detect available cameras
     - Test backend connection
     - Run sample detection on 1 LED
   - Tooltips on all controls
   - "Help" button → opens documentation in browser

5. Performance optimizations:
   - Frame queue with drop-old-frames policy (prevent backlog)
   - Lazy loading for historical views (don't render until tab opened)
   - Configurable update rates (GUI refresh vs detector FPS)

**Testing:**
- Usability testing with new users
- Test all error scenarios (crash detector, disconnect camera, etc.)
- Performance profiling with large LED counts

---

## 4. Critical Integration Points

### **Integration Point 1: Frame Capture from DetectorProcess**

**Current code** (`detector_process.py:225-228`):
```python
cv2.imshow("MariMapper - Detector", drawn_image)
if cv2.waitKey(1) & 0xFF == ord("q"):
    raise KeyboardInterrupt
```

**Modified code**:
```python
if self.frame_queue is not None:
    # GUI mode: Send frame via queue
    if not self.frame_queue.full():
        self.frame_queue.put(drawn_image)
else:
    # CLI mode: Show window
    cv2.imshow("MariMapper - Detector", drawn_image)
    if cv2.waitKey(1) & 0xFF == ord("q"):
        raise KeyboardInterrupt
```

**Changes to constructor** (`detector_process.py:37`):
```python
def __init__(
    self,
    # ... existing params ...
    frame_queue: Optional[Queue] = None  # NEW
):
    self.frame_queue = frame_queue
```

---

### **Integration Point 2: Scanner Control from GUI**

**Current code** (`scanner.py:182`):
```python
def mainloop(self):
    while True:
        if not self.get_user_confirmation():
            break
        # ... detection logic ...
```

**New approach**: Expose methods, call from GUI:
```python
# In scanner.py, keep existing methods but remove mainloop's input()

# In GUI worker thread:
def run_scan(self):
    led_from, led_to = self.get_led_range_from_gui()
    self.scanner.detector.detect(led_from, led_to, self.view_id)
    self.scanner.wait_for_scan()
    self.view_id += 1
    self.emit_scan_complete_signal()
```

---

### **Integration Point 3: Status Monitoring Thread**

**New class** (`marimapper/gui/worker.py`):
```python
class StatusMonitorThread(QThread):
    frame_ready = pyqtSignal(np.ndarray)
    led_detected = pyqtSignal(object)  # LED2D
    reconstruction_updated = pyqtSignal(dict)  # LED ID → LEDInfo
    process_crashed = pyqtSignal(str)  # Process name

    def __init__(self, scanner, frame_queue):
        super().__init__()
        self.scanner = scanner
        self.frame_queue = frame_queue
        self.running = True

    def run(self):
        while self.running:
            # Poll frame queue
            if not self.frame_queue.empty():
                frame = self.frame_queue.get()
                self.frame_ready.emit(frame)

            # Poll detection queue (subscribe to Queue2D)
            # ... emit led_detected ...

            # Poll 3D info queue
            # ... emit reconstruction_updated ...

            # Check process health
            if not self.scanner.check_for_crash():
                self.process_crashed.emit("DetectorProcess")

            time.sleep(0.033)  # 30 Hz polling
```

---

### **Integration Point 4: Respecting `set_start_method("spawn")`**

**Critical constraint** from `scanner.py:66`:
```python
if __name__ == "__main__":
    set_start_method("spawn", force=True)
```

**GUI entry point** must do this **before** importing PyQt:
```python
# marimapper/scripts/gui_cli.py
import multiprocessing
if __name__ == "__main__":
    multiprocessing.set_start_method("spawn", force=True)

    from PyQt6.QtWidgets import QApplication  # Import AFTER
    from marimapper.gui.main_window import MainWindow

    app = QApplication(sys.argv)
    # ... rest of GUI init ...
```

---

## 5. Module Structure

```
marimapper/
├── gui/
│   ├── __init__.py
│   ├── main_window.py           # QMainWindow subclass (main app)
│   ├── worker.py                # QThread for status monitoring
│   ├── signals.py               # Custom signal definitions
│   ├── widgets/
│   │   ├── __init__.py
│   │   ├── detector_widget.py   # Video display widget
│   │   ├── control_panel.py     # Sidebar controls
│   │   ├── log_widget.py        # Colored log output
│   │   ├── status_table.py      # LED reconstruction status table
│   │   └── camera_pose_widget.py  # 2D camera pose view
│   ├── dialogs/
│   │   ├── __init__.py
│   │   ├── preset_dialog.py     # Save/Load presets
│   │   ├── batch_scan_wizard.py # Multi-view wizard
│   │   └── error_dialog.py      # Error handling
│   ├── resources/
│   │   ├── icons/               # UI icons
│   │   ├── styles/
│   │   │   ├── dark.qss         # Dark mode stylesheet
│   │   │   └── light.qss        # Light mode stylesheet
│   │   └── default_config.json  # Default settings
│   └── utils/
│       ├── __init__.py
│       ├── image_utils.py       # OpenCV ↔ QImage conversion
│       └── config_manager.py    # Preset save/load logic
├── scripts/
│   ├── scanner_cli.py           # Existing CLI (unchanged)
│   └── gui_cli.py               # NEW: GUI entry point
└── [existing files unchanged]
```

**Entry point in `pyproject.toml`**:
```toml
[project.scripts]
marimapper = "marimapper.scripts.scanner_cli:main"
marimapper-gui = "marimapper.scripts.gui_cli:main"  # NEW
```

---

## 6. Maintaining Modularity

### **Principle: Separation of Concerns**

1. **Core CV code remains untouched**:
   - `detector.py`, `sfm.py`, `camera.py`, `led.py` → **zero changes**
   - All CV logic stays in existing modules

2. **Process classes get optional GUI hooks**:
   - Constructor accepts optional `frame_queue` parameter
   - Falls back to CLI behavior if `None`
   - Example: `DetectorProcess(frame_queue=None)` for CLI mode

3. **GUI is a separate layer**:
   - Lives in `marimapper/gui/` module
   - Can be updated independently
   - CLI and GUI share same `Scanner` class

4. **Configuration abstraction**:
   - `ConfigManager` class converts between:
     - CLI argparse namespace
     - GUI dialog inputs
     - JSON preset files
   - Scanner constructor accepts simple dict/namespace (agnostic to source)

---

## 7. Testing Strategy

### **Phase 1 (Foundation):**
- ✅ Unit tests for image conversion (`cv2` → `QImage`)
- ✅ Integration test: Launch GUI, start scan, verify CSV output matches CLI
- ✅ Regression test: Run existing pytest suite, ensure no breakage
- ✅ Manual test: Run on Windows and Linux with USB camera

### **Phase 2 (Controls):**
- ✅ Unit tests for signal/slot connections
- ✅ Test exposure slider: Verify camera response to changes
- ✅ Test status table: Mock Queue3DInfo data, verify display
- ✅ Performance test: Check GUI responsiveness during scan

### **Phase 3 (Multi-View):**
- ✅ Memory leak test: Capture 50 views, monitor RAM usage
- ✅ Test historical view rendering
- ✅ Test 3D viewer commands (if implemented)

### **Phase 4 (Advanced):**
- ✅ Test preset save/load: Verify all settings restored
- ✅ Test batch scan: Verify countdown timer accuracy
- ✅ Test export formats: Validate JSON/NPY outputs

### **Phase 5 (Polish):**
- ✅ Usability testing: Give to 3 users, collect feedback
- ✅ Error injection tests: Simulate all failure modes
- ✅ Cross-platform testing: Windows, Linux, macOS

**Automated testing approach:**
- Use `pytest-qt` plugin for Qt-specific tests
- Mock multiprocessing queues with `queue.Queue` for unit tests
- Keep integration tests separate (require hardware)

---

## 8. Risk Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Breaking CV functionality** | Critical | Extensive regression testing; keep CLI mode as fallback |
| **Frame queue backlog** | Performance | Drop old frames; configurable queue size (maxsize=3) |
| **Open3D embedding failure** | Medium | Phase 3 starts with separate window (known working) |
| **Cross-platform issues** | High | Test on all platforms early; use Qt for portability |
| **`set_start_method` timing** | Critical | Document clearly; add assertion check in code |
| **Memory leaks from historical views** | Medium | Configurable view limit; test with stress scenarios |

---

## 9. Dependencies

**New dependencies** (add to `pyproject.toml`):
```toml
[project.optional-dependencies]
gui = [
    "PyQt6 >= 6.4.0",
    "PyQt6-Qt6 >= 6.4.0",
]
```

**Install command**:
```bash
uv pip install -e ".[gui]"
```

**Alternative** (LGPL licensing):
Replace `PyQt6` with `PySide6` (same API, different license)

---

## 10. Timeline & Priorities

### **Recommended Development Order:**

1. **Phase 1 (Foundation)** - ~1-2 weeks
   - Gets basic GUI working with video display
   - Validates integration approach
   - **BLOCKER for all other phases**

2. **Phase 2 (Controls)** - ~1 week
   - Adds most-needed usability features
   - Status monitoring is high value

3. **Phase 5 (Polish)** - ~3-4 days
   - Make it look good before adding complexity
   - Easier to refine styling early

4. **Phase 3 (Multi-View)** - ~1 week
   - Nice-to-have, not critical
   - Separate 3D window approach is low-risk

5. **Phase 4 (Advanced)** - ~1 week
   - Power user features
   - Can be incremental additions

**Minimum Viable GUI**: Phase 1 + basic Phase 2 (control panel + status)

---

## 11. Documentation Updates

**Files to update:**
1. `README.md`:
   - Add GUI mode instructions
   - Add screenshot of GUI
   - Update installation to include `[gui]` extra

2. `CLAUDE.md`:
   - Document GUI architecture
   - Add entry point: `marimapper-gui`
   - Document frame_queue integration point

3. New `docs/gui.md`:
   - User guide for GUI mode
   - Keyboard shortcuts
   - Troubleshooting GUI issues

4. Docstrings:
   - Add to all new GUI classes
   - Document signal parameters

---

## Summary

This plan creates a **non-invasive GUI wrapper** around MariMapper's robust multi-process architecture:

✅ **Modularity**: GUI lives in separate `marimapper/gui/` module
✅ **Backward compatibility**: CLI mode unchanged, GUI is optional
✅ **CV safety**: Core detection/reconstruction code untouched
✅ **Extensibility**: Phase-based approach allows incremental features
✅ **User experience**: Modern PyQt6 interface with controls, status, and visualization

**Next steps:**
1. Choose license (PyQt6 = GPL, PySide6 = LGPL)
2. Approve framework choice and architecture
3. Begin Phase 1 implementation
