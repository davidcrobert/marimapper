"""
Main window for MariMapper GUI.

This is the primary window that integrates all GUI components and manages
the Scanner instance.
"""

from multiprocessing import Queue
from pathlib import Path
import cv2
import json
from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QMessageBox,
    QTabWidget,
)
from PyQt6.QtCore import Qt, pyqtSlot, QTimer, QThread, pyqtSignal

from marimapper.scanner import Scanner
from marimapper.detector_process import CameraCommand
from marimapper.gui.signals import MariMapperSignals
from marimapper.file_tools import load_3d_leds_from_file
from marimapper.gui.widgets.detector_widget import DetectorWidget
from marimapper.gui.widgets.control_panel import ControlPanel
from marimapper.gui.widgets.log_widget import LogWidget
from marimapper.gui.widgets.status_table import StatusTable
from marimapper.gui.widgets.visualizer_3d_widget import Visualizer3DWidget
from marimapper.gui.worker import StatusMonitorThread


class ScannerInitThread(QThread):
    """Background thread for initializing the Scanner (which can block)."""

    finished = pyqtSignal(object, int)  # scanner, led_count
    error = pyqtSignal(str)  # error message

    def __init__(self, scanner_args, frame_queue):
        super().__init__()
        self.scanner_args = scanner_args
        self.frame_queue = frame_queue

    def run(self):
        """Run scanner initialization in background thread."""
        try:
            import sys
            print("ScannerInitThread: Creating Scanner...", file=sys.stderr, flush=True)

            # Create Scanner instance
            scanner = Scanner(
                output_dir=self.scanner_args.output_dir,
                device=self.scanner_args.device,
                exposure=self.scanner_args.dark_exposure,
                threshold=self.scanner_args.threshold,
                backend_factory=self.scanner_args.backend_factory,
                led_start=self.scanner_args.led_start,
                led_end=self.scanner_args.led_end,
                interpolation_max_fill=self.scanner_args.interpolation_max_fill,
                interpolation_max_error=self.scanner_args.interpolation_max_error,
                check_movement=self.scanner_args.check_movement,
                camera_model_name=self.scanner_args.camera_model,
                axis_config=self.scanner_args.axis_config,
                frame_queue=self.frame_queue,
            )

            print("ScannerInitThread: Scanner created successfully!", file=sys.stderr, flush=True)

            # Get LED count from cached value (Scanner.__init__ already called get_led_count())
            led_count = scanner.led_count
            print(f"ScannerInitThread: LED count: {led_count}", file=sys.stderr, flush=True)

            # Check for error value
            if led_count < 0:
                raise Exception("Detector process failed to initialize. Check console for error details (likely camera unavailable).")

            # Emit success signal
            self.finished.emit(scanner, led_count)

        except Exception as e:
            import traceback
            print(f"ScannerInitThread ERROR: {e}", file=sys.stderr, flush=True)
            traceback.print_exc()
            # Emit error signal
            self.error.emit(str(e))


class MainWindow(QMainWindow):
    """Main application window for MariMapper GUI."""

    def __init__(self, scanner_args):
        """
        Initialize the main window.

        Args:
            scanner_args: Namespace containing scanner configuration arguments
        """
        super().__init__()
        self.scanner_args = scanner_args
        self.scanner = None
        self.frame_queue = None
        self.monitor_thread = None
        self.init_thread = None
        self.current_view_id = 0
        self.is_video_maximized = False

        # Mask management (per-camera)
        self.current_masks = {}  # {camera_index: numpy_array}
        self.mask_resolutions = {}  # {camera_index: (height, width)}
        self.active_camera_index = 0  # Currently displayed camera for mask editing
        self.camera_count = 1  # Number of cameras (1 for single, N for multi)

        # Create signals
        self.signals = MariMapperSignals()

        self.init_ui()
        self.connect_signals()

        # Start scanner initialization in background after window is shown
        QTimer.singleShot(100, self.start_scanner_init)

    def init_ui(self):
        """Initialize the user interface."""
        self.setWindowTitle("MariMapper - LED Mapping Tool")
        self.setGeometry(100, 100, 1200, 800)

        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Main layout
        main_layout = QHBoxLayout()

        # Left side: Tabbed view and log (vertical splitter)
        self.left_splitter = QSplitter(Qt.Orientation.Vertical)

        # Tab widget for Video Feed and 3D View
        self.tab_widget = QTabWidget()

        # Video display widget
        self.detector_widget = DetectorWidget()
        self.tab_widget.addTab(self.detector_widget, "Video Feed")

        # 3D visualization widget
        self.visualizer_3d_widget = Visualizer3DWidget()
        self.tab_widget.addTab(self.visualizer_3d_widget, "3D View")

        self.left_splitter.addWidget(self.tab_widget)

        # Log widget
        self.log_widget = LogWidget()
        self.left_splitter.addWidget(self.log_widget)

        # Set initial sizes (tabs take more space, log reasonably tall)
        self.left_splitter.setSizes([600, 200])

        # Right side: Control panel and status table
        self.right_widget = QWidget()
        right_layout = QVBoxLayout()
        right_layout.setContentsMargins(0, 0, 0, 0)

        self.control_panel = ControlPanel()
        self.control_panel.start_button.setEnabled(False)  # Disable until scanner ready
        right_layout.addWidget(self.control_panel)

        # LED status table
        self.status_table = StatusTable()
        right_layout.addWidget(self.status_table)

        # Give the status table most of the vertical space
        right_layout.setStretch(0, 1)
        right_layout.setStretch(1, 3)

        self.right_widget.setLayout(right_layout)

        # Add to main layout
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.addWidget(self.left_splitter)
        self.main_splitter.addWidget(self.right_widget)

        # Set initial sizes (more width for controls + status table)
        self.main_splitter.setSizes([700, 500])
        # Store the original sizes for restore
        self.original_splitter_sizes = [700, 500]

        main_layout.addWidget(self.main_splitter)
        central_widget.setLayout(main_layout)

        # Menu bar
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("&File")
        exit_action = file_menu.addAction("E&xit")
        exit_action.triggered.connect(self.close)

        # Help menu
        help_menu = menubar.addMenu("&Help")
        about_action = help_menu.addAction("&About")
        about_action.triggered.connect(self.show_about)

        # Status bar
        self.statusBar().showMessage("Initializing...")

    def connect_signals(self):
        """Connect Qt signals to slots."""
        # Connect control panel signals
        self.control_panel.start_scan_requested.connect(self.start_scan)
        self.control_panel.stop_scan_requested.connect(self.stop_scan)
        self.control_panel.exposure_dark_requested.connect(self.set_exposure_dark)
        self.control_panel.exposure_bright_requested.connect(self.set_exposure_bright)
        self.control_panel.threshold_changed.connect(self.set_threshold)
        self.control_panel.all_off_requested.connect(self.set_all_off)
        self.control_panel.all_on_requested.connect(self.set_all_on)

        # Connect status table signals
        self.status_table.led_toggle_requested.connect(self.set_individual_led)
        self.status_table.bulk_led_toggle_requested.connect(self.set_bulk_leds)
        self.status_table.manual_selection_changed.connect(self.visualizer_3d_widget.set_active_leds)

        # Connect control panel to status table for visual state updates
        self.control_panel.all_off_requested.connect(self.status_table.set_all_off_state)
        self.control_panel.all_on_requested.connect(self.status_table.set_all_on_state)

        # Connect detector widget signals
        self.detector_widget.maximize_toggled.connect(self.toggle_video_maximize)

        # Connect mask control signals
        self.control_panel.paint_mode_toggled.connect(
            self.detector_widget.set_painting_mode
        )
        self.control_panel.brush_size_changed.connect(self.detector_widget.set_brush_size)
        self.control_panel.mask_visibility_toggled.connect(
            self.detector_widget.set_mask_visibility
        )
        self.control_panel.mask_clear_requested.connect(self.on_clear_mask)
        self.control_panel.mask_save_requested.connect(self.on_save_mask)
        self.control_panel.mask_load_requested.connect(self.on_load_mask)
        self.control_panel.camera_selected.connect(self.on_camera_selected)

        # Connect detector widget mask signals
        self.detector_widget.mask_updated.connect(self.on_mask_updated)

        # Connect worker thread signals
        self.signals.frame_ready.connect(self.detector_widget.update_frame)
        self.signals.log_message.connect(self.log_widget.add_message)
        self.signals.scan_completed.connect(self.on_scan_completed)
        self.signals.scan_failed.connect(self.on_scan_failed)
        self.signals.reconstruction_updated.connect(self.status_table.update_led_info)
        self.signals.points_3d_updated.connect(self.visualizer_3d_widget.update_3d_data)
        self.visualizer_3d_widget.led_clicked.connect(self.on_visualizer_led_clicked)

    def start_scanner_init(self):
        """Start scanner initialization in background thread."""
        self.log_widget.log_info("Testing change...")
        self.log_widget.log_info("Initializing scanner...")

        # Create frame queue for receiving video frames
        self.frame_queue = Queue(maxsize=3)  # Small queue to avoid backlog

        # Create and start initialization thread
        self.init_thread = ScannerInitThread(self.scanner_args, self.frame_queue)
        self.init_thread.finished.connect(self.on_scanner_ready)
        self.init_thread.error.connect(self.on_scanner_error)
        self.init_thread.start()

    @pyqtSlot(object, int)
    def on_scanner_ready(self, scanner, led_count):
        """
        Called when scanner initialization completes successfully.

        Args:
            scanner: The initialized Scanner instance
            led_count: Number of LEDs in the system
        """
        self.scanner = scanner
        self.control_panel.set_led_count(led_count)

        # Set threshold slider to match scanner's initial threshold
        initial_threshold = self.scanner_args.threshold
        self.control_panel.threshold_slider.setValue(initial_threshold)

        self.log_widget.log_success(f"Scanner initialized with {led_count} LEDs")

        # Create detector update queue and 3D queues
        detector_update_queue = self.scanner.create_detector_update_queue()
        info_3d_queue = self.scanner.get_3d_info_queue()
        data_3d_queue = self.scanner.get_3d_data_queue()

        self.log_widget.log_info(f"3D info queue created: {info_3d_queue is not None}")
        self.log_widget.log_info(f"3D data queue created: {data_3d_queue is not None}")

        # Start status monitor thread
        self.monitor_thread = StatusMonitorThread(
            self.signals, self.frame_queue, detector_update_queue, info_3d_queue, data_3d_queue
        )
        self.monitor_thread.start()

        self.log_widget.log_info("Monitor thread started, watching for 3D info updates...")

        # Log diagnostic information
        self.log_widget.log_info(f"Detector process alive: {scanner.detector.is_alive()}")
        self.log_widget.log_info(f"Frame queue created: {self.frame_queue is not None}")

        # Enable controls now that scanner is ready
        self.control_panel.start_button.setEnabled(True)
        self.statusBar().showMessage("Scanner ready")

        # Detect camera count for multi-camera support
        if hasattr(scanner, "detector_workers") and scanner.detector_workers:
            # Multi-camera mode
            self.camera_count = len(scanner.detector_workers)
            self.log_widget.log_info(f"Multi-camera mode detected: {self.camera_count} cameras")
        else:
            # Single camera mode
            self.camera_count = 1
            self.log_widget.log_info("Single camera mode")

        # Initialize camera selector if multi-camera
        if self.camera_count > 1:
            self.control_panel.set_camera_count(self.camera_count)

        # Auto-load saved masks
        self.auto_load_masks()

        # Auto-load existing 3D data
        self.auto_load_3d_data()

    @pyqtSlot(str)
    def on_scanner_error(self, error_msg):
        """
        Called when scanner initialization fails.

        Args:
            error_msg: Error message describing the failure
        """
        self.log_widget.log_error(f"Failed to initialize scanner: {error_msg}")
        self.statusBar().showMessage("Initialization failed")
        QMessageBox.critical(
            self,
            "Initialization Error",
            f"Failed to initialize scanner:\n{error_msg}\n\nPlease check camera and backend connections.",
        )

    @pyqtSlot(int, int)
    def start_scan(self, led_from: int, led_to: int):
        """
        Start a scan with the specified LED range.

        Args:
            led_from: First LED ID to scan
            led_to: Last LED ID to scan (exclusive)
        """
        if self.scanner is None:
            self.log_widget.log_error("Scanner not initialized")
            return

        try:
            self.log_widget.log_info(f"Starting scan: LEDs {led_from} to {led_to}, view {self.current_view_id}")
            self.scanner.detector.detect(led_from, led_to, self.current_view_id)
            self.statusBar().showMessage(f"Scanning LEDs {led_from}-{led_to}...")

        except Exception as e:
            self.log_widget.log_error(f"Failed to start scan: {str(e)}")
            self.control_panel.scan_failed(str(e))

    @pyqtSlot()
    def stop_scan(self):
        """Stop the current scan."""
        if self.scanner is None:
            self.log_widget.log_error("Scanner not initialized")
            return

        try:
            camera_queue = self.scanner.get_camera_command_queue()
            if camera_queue is not None:
                camera_queue.put(CameraCommand.CANCEL_SCAN)
                self.log_widget.log_info("Scan cancellation requested")
                self.statusBar().showMessage("Cancelling scan...")
            else:
                self.log_widget.log_warning("Cannot cancel scan in multi-camera mode (not yet supported)")
        except Exception as e:
            self.log_widget.log_error(f"Failed to cancel scan: {str(e)}")

    @pyqtSlot()
    def set_exposure_dark(self):
        """Set camera to dark mode (low exposure for LED detection)."""
        if self.scanner is None:
            self.log_widget.log_error("Scanner not initialized")
            return

        try:
            from marimapper.detector_process import CameraCommand
            camera_queue = self.scanner.get_camera_command_queue()
            camera_queue.put(CameraCommand.SET_DARK)
            self.log_widget.log_info("Camera set to DARK mode")
            self.statusBar().showMessage("Camera: Dark mode")
        except Exception as e:
            self.log_widget.log_error(f"Failed to set dark mode: {str(e)}")

    @pyqtSlot()
    def set_exposure_bright(self):
        """Set camera to bright mode (normal exposure)."""
        if self.scanner is None:
            self.log_widget.log_error("Scanner not initialized")
            return

        try:
            from marimapper.detector_process import CameraCommand
            camera_queue = self.scanner.get_camera_command_queue()
            camera_queue.put(CameraCommand.SET_BRIGHT)
            self.log_widget.log_info("Camera set to BRIGHT mode")
            self.statusBar().showMessage("Camera: Bright mode")
        except Exception as e:
            self.log_widget.log_error(f"Failed to set bright mode: {str(e)}")

    @pyqtSlot(int)
    def set_threshold(self, value: int):
        """Set detection threshold."""
        if self.scanner is None:
            self.log_widget.log_error("Scanner not initialized")
            return

        try:
            from marimapper.detector_process import CameraCommand
            camera_queue = self.scanner.get_camera_command_queue()
            camera_queue.put((CameraCommand.SET_THRESHOLD, value))
            self.log_widget.log_info(f"Detection threshold set to {value}")
            self.statusBar().showMessage(f"Threshold: {value}")
        except Exception as e:
            self.log_widget.log_error(f"Failed to set threshold: {str(e)}")

    @pyqtSlot()
    def set_all_off(self):
        """Turn off all LEDs/pixels."""
        if self.scanner is None:
            self.log_widget.log_error("Scanner not initialized")
            return

        try:
            from marimapper.detector_process import CameraCommand
            camera_queue = self.scanner.get_camera_command_queue()
            camera_queue.put(CameraCommand.ALL_OFF)
            self.log_widget.log_info("All LEDs off")
            self.statusBar().showMessage("LEDs: All off")
        except Exception as e:
            self.log_widget.log_error(f"Failed to turn LEDs off: {str(e)}")

    @pyqtSlot(int, bool)
    def set_individual_led(self, led_id: int, turn_on: bool):
        """Turn on or off an individual LED."""
        if self.scanner is None:
            self.log_widget.log_error("Scanner not initialized")
            return

        try:
            from marimapper.detector_process import CameraCommand
            camera_queue = self.scanner.get_camera_command_queue()
            camera_queue.put((CameraCommand.SET_LED, (led_id, turn_on)))
            status = "ON" if turn_on else "OFF"
            self.log_widget.log_info(f"LED {led_id} turned {status}")
        except Exception as e:
            self.log_widget.log_error(f"Failed to control LED {led_id}: {str(e)}")

    @pyqtSlot(list)
    def set_bulk_leds(self, changes: list):
        """Turn on or off multiple LEDs at once.

        Args:
            changes: List of (led_id, turn_on) tuples
        """
        if self.scanner is None:
            self.log_widget.log_error("Scanner not initialized")
            return

        try:
            from marimapper.detector_process import CameraCommand
            camera_queue = self.scanner.get_camera_command_queue()
            camera_queue.put((CameraCommand.SET_LEDS_BULK, changes))

            on_count = sum(1 for _, state in changes if state)
            off_count = len(changes) - on_count
            self.log_widget.log_info(f"Bulk LED control: {on_count} ON, {off_count} OFF")
        except Exception as e:
            self.log_widget.log_error(f"Failed to control LEDs in bulk: {str(e)}")

    @pyqtSlot()
    def set_all_on(self):
        """Turn on all LEDs/pixels."""
        if self.scanner is None:
            self.log_widget.log_error("Scanner not initialized")
            return

        try:
            from marimapper.detector_process import CameraCommand
            camera_queue = self.scanner.get_camera_command_queue()
            camera_queue.put(CameraCommand.ALL_ON)
            self.log_widget.log_info("All LEDs on")
            self.statusBar().showMessage("LEDs: All on")
        except Exception as e:
            self.log_widget.log_error(f"Failed to turn LEDs on: {str(e)}")

    @pyqtSlot(int)
    def on_visualizer_led_clicked(self, led_id: int):
        """Handle clicks on 3D points by toggling the corresponding LED."""
        turn_on = led_id not in self.status_table.manual_on_leds
        # Update table state (emits led_toggle_requested which routes to set_individual_led)
        self.status_table.set_led_state(led_id, turn_on)

    @pyqtSlot(bool)
    def toggle_video_maximize(self, maximize: bool):
        """
        Toggle video panel maximize/minimize.

        Args:
            maximize: True to maximize video, False to restore layout
        """
        self.is_video_maximized = maximize

        if maximize:
            # Hide the right panel and log widget
            self.right_widget.hide()
            self.log_widget.hide()
            self.statusBar().showMessage("Video maximized (double-click or click button to restore)")
        else:
            # Restore all panels
            self.right_widget.show()
            self.log_widget.show()
            # Restore splitter sizes
            self.main_splitter.setSizes(self.original_splitter_sizes)
            self.statusBar().showMessage("Video restored")

    @pyqtSlot(int)
    def on_scan_completed(self, view_id: int):
        """
        Handle scan completion.

        Args:
            view_id: ID of the completed view
        """
        self.control_panel.scan_completed()
        self.current_view_id += 1
        self.statusBar().showMessage(f"Scan completed for view {view_id}")

    @pyqtSlot(str)
    def on_scan_failed(self, error_msg: str):
        """
        Handle scan failure.

        Args:
            error_msg: Error message describing the failure
        """
        self.control_panel.scan_failed(error_msg)
        self.statusBar().showMessage("Scan failed")

    def show_about(self):
        """Show the about dialog."""
        QMessageBox.about(
            self,
            "About MariMapper",
            "<h3>MariMapper LED Mapping Tool</h3>"
            "<p>A tool to map addressable LEDs into 2D and 3D space using only your webcam.</p>"
            "<p>This GUI interface provides an intuitive way to capture and map LED positions.</p>"
            "<p><b>Phase 1:</b> Basic GUI with video display and scan controls</p>",
        )

    @pyqtSlot(object)
    def on_mask_updated(self, mask_numpy):
        """Handle mask update from painting."""
        if mask_numpy is None:
            return

        # Store mask for active camera
        self.current_masks[self.active_camera_index] = mask_numpy

        # Get current video resolution from detector widget
        if self.detector_widget.video_label.pixmap():
            pixmap = self.detector_widget.video_label.pixmap()
            self.mask_resolutions[self.active_camera_index] = (
                pixmap.height(),
                pixmap.width(),
            )

        # Send to appropriate detector process/worker
        self.send_mask_to_detector(self.active_camera_index)

        self.log_widget.log_info(
            f"Mask updated for camera {self.active_camera_index}"
        )

    @pyqtSlot()
    def on_clear_mask(self):
        """Clear the current mask."""
        # Clear mask for active camera
        self.current_masks.pop(self.active_camera_index, None)
        self.mask_resolutions.pop(self.active_camera_index, None)
        self.detector_widget.set_mask_from_numpy(None)

        # Send clear command to detector
        self.send_mask_to_detector(self.active_camera_index)

        self.log_widget.log_success(
            f"Mask cleared for camera {self.active_camera_index}"
        )

    @pyqtSlot()
    def on_save_mask(self):
        """Save mask to file."""
        if self.active_camera_index not in self.current_masks:
            self.log_widget.log_warning("No mask to save")
            return

        try:
            # Get mask file path for active camera
            mask_file_path = (
                Path(self.scanner_args.output_dir)
                / f"detection_mask_{self.active_camera_index}.png"
            )

            # Save as PNG (lossless, good for binary data)
            cv2.imwrite(
                str(mask_file_path), self.current_masks[self.active_camera_index]
            )

            # Also save resolution metadata
            meta_path = mask_file_path.with_suffix(".json")
            with open(meta_path, "w") as f:
                json.dump(
                    {
                        "resolution": self.mask_resolutions.get(
                            self.active_camera_index
                        ),
                        "camera_index": self.active_camera_index,
                    },
                    f,
                )

            self.log_widget.log_success(
                f"Mask saved to {mask_file_path.name}"
            )

        except Exception as e:
            self.log_widget.log_error(f"Failed to save mask: {e}")

    @pyqtSlot()
    def on_load_mask(self):
        """Load mask from file."""
        try:
            # Get mask file path for active camera
            mask_file_path = (
                Path(self.scanner_args.output_dir)
                / f"detection_mask_{self.active_camera_index}.png"
            )

            if not mask_file_path.exists():
                self.log_widget.log_warning(
                    f"No mask file found for camera {self.active_camera_index}"
                )
                return

            # Load mask image
            mask = cv2.imread(str(mask_file_path), cv2.IMREAD_GRAYSCALE)

            # Load resolution metadata if available
            meta_path = mask_file_path.with_suffix(".json")
            if meta_path.exists():
                with open(meta_path, "r") as f:
                    meta = json.load(f)
                    self.mask_resolutions[self.active_camera_index] = tuple(
                        meta["resolution"]
                    )
            else:
                self.mask_resolutions[self.active_camera_index] = (
                    mask.shape[0],
                    mask.shape[1],
                )

            self.current_masks[self.active_camera_index] = mask

            # Update detector widget
            self.detector_widget.set_mask_from_numpy(mask)

            # Send to detector process
            self.send_mask_to_detector(self.active_camera_index)

            self.log_widget.log_success(
                f"Mask loaded from {mask_file_path.name}"
            )

        except Exception as e:
            self.log_widget.log_error(f"Failed to load mask: {e}")

    @pyqtSlot(int)
    def on_camera_selected(self, camera_index: int):
        """Switch active camera for mask editing."""
        self.active_camera_index = camera_index

        # Load that camera's mask into DetectorWidget
        if camera_index in self.current_masks:
            self.detector_widget.set_mask_from_numpy(
                self.current_masks[camera_index]
            )
            self.log_widget.log_info(
                f"Loaded mask for camera {camera_index}"
            )
        else:
            self.detector_widget.set_mask_from_numpy(None)
            self.log_widget.log_info(
                f"No mask for camera {camera_index}"
            )

    def send_mask_to_detector(self, camera_index: int):
        """Send mask to detector process via CameraCommand."""
        if self.scanner is None:
            return

        try:
            # Get mask data for this camera
            mask_data = self.current_masks.get(camera_index)
            mask_res = self.mask_resolutions.get(camera_index)

            # Prepare mask dict (None mask_data will clear mask)
            mask_dict = {"mask": mask_data, "resolution": mask_res}

            # For single-camera: send to DetectorProcess camera_command_queue
            if self.camera_count == 1:
                camera_queue = self.scanner.get_camera_command_queue()
                camera_queue.put((CameraCommand.SET_MASK, mask_dict))
                self.log_widget.log_info("Mask sent to detector process")
            else:
                # For multi-camera: send to specific DetectorWorkerProcess
                worker_queue = self.scanner.get_worker_command_queue(camera_index)
                if worker_queue is not None:
                    worker_queue.put(("SET_MASK", mask_dict))
                    self.log_widget.log_info(
                        f"Mask sent to camera {camera_index} worker"
                    )
                else:
                    self.log_widget.log_error(
                        f"Failed to get command queue for camera {camera_index}"
                    )

        except Exception as e:
            self.log_widget.log_error(
                f"Failed to send mask to detector: {e}"
            )

    def auto_load_masks(self):
        """Auto-load saved masks for all cameras on startup."""
        for camera_index in range(self.camera_count):
            mask_file_path = (
                Path(self.scanner_args.output_dir)
                / f"detection_mask_{camera_index}.png"
            )

            if mask_file_path.exists():
                self.log_widget.log_info(
                    f"Auto-loading mask for camera {camera_index}..."
                )
                # Temporarily set active camera to load the mask
                old_active = self.active_camera_index
                self.active_camera_index = camera_index
                self.on_load_mask()
                self.active_camera_index = old_active

        # Ensure the active camera's mask is displayed
        if self.active_camera_index in self.current_masks:
            self.detector_widget.set_mask_from_numpy(
                self.current_masks[self.active_camera_index]
            )

    def auto_load_3d_data(self):
        """Auto-load existing 3D LED data on startup."""
        led_map_3d_path = Path(self.scanner_args.output_dir) / "led_map_3d.csv"

        if not led_map_3d_path.exists():
            self.log_widget.log_info("No existing 3D data found")
            return

        try:
            self.log_widget.log_info("Loading existing 3D data...")
            leds_3d = load_3d_leds_from_file(led_map_3d_path)

            if leds_3d is not None and len(leds_3d) > 0:
                self.log_widget.log_success(f"Loaded {len(leds_3d)} LEDs from existing 3D map")
                # Display in 3D widget
                self.visualizer_3d_widget.update_3d_data(leds_3d)
                # Optionally switch to 3D View tab to show the loaded data
                self.tab_widget.setCurrentIndex(1)  # Switch to 3D View tab
                self.log_widget.log_info("Switched to 3D View tab to display loaded data")
            else:
                self.log_widget.log_warning("3D data file exists but contains no valid data")

        except Exception as e:
            self.log_widget.log_error(f"Failed to load 3D data: {e}")

    def closeEvent(self, event):
        """Handle window close event - clean up scanner and threads."""
        self.log_widget.log_info("Shutting down...")
        self.statusBar().showMessage("Closing...")

        # Stop initialization thread if still running
        if self.init_thread is not None and self.init_thread.isRunning():
            self.log_widget.log_info("Stopping initialization thread...")
            if not self.init_thread.wait(2000):  # Wait up to 2 seconds
                self.log_widget.log_warning("Initialization thread did not stop in time")

        # Stop monitor thread
        if self.monitor_thread is not None:
            self.log_widget.log_info("Stopping monitor thread...")
            self.monitor_thread.stop()
            if not self.monitor_thread.wait(1000):  # Wait up to 1 second
                self.log_widget.log_warning("Monitor thread did not stop in time")

        # Close scanner (this stops all child processes)
        if self.scanner is not None:
            try:
                self.log_widget.log_info("Closing scanner processes...")
                self.scanner.close()
                self.log_widget.log_success("Scanner closed successfully")
            except Exception as e:
                self.log_widget.log_error(f"Error closing scanner: {str(e)}")

        self.log_widget.log_success("Shutdown complete")
        event.accept()
