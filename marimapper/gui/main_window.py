"""
Main window for MariMapper GUI.

This is the primary window that integrates all GUI components and manages
the Scanner instance.
"""

from multiprocessing import Queue
from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QMessageBox,
)
from PyQt6.QtCore import Qt, pyqtSlot, QTimer, QThread, pyqtSignal

from marimapper.scanner import Scanner
from marimapper.gui.signals import MariMapperSignals
from marimapper.gui.widgets.detector_widget import DetectorWidget
from marimapper.gui.widgets.control_panel import ControlPanel
from marimapper.gui.widgets.log_widget import LogWidget
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

            # Get LED count (this blocks waiting for detector process)
            led_count = scanner.detector.get_led_count()

            # Emit success signal
            self.finished.emit(scanner, led_count)

        except Exception as e:
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

        # Left side: Video display and log (vertical splitter)
        left_splitter = QSplitter(Qt.Orientation.Vertical)

        # Video display widget
        self.detector_widget = DetectorWidget()
        left_splitter.addWidget(self.detector_widget)

        # Log widget
        self.log_widget = LogWidget()
        left_splitter.addWidget(self.log_widget)

        # Set initial sizes (video takes more space)
        left_splitter.setSizes([600, 200])

        # Right side: Control panel
        self.control_panel = ControlPanel()
        self.control_panel.start_button.setEnabled(False)  # Disable until scanner ready

        # Add to main layout
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_splitter.addWidget(left_splitter)
        main_splitter.addWidget(self.control_panel)

        # Set initial sizes (video/log takes more space than controls)
        main_splitter.setSizes([900, 300])

        main_layout.addWidget(main_splitter)
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

        # Connect worker thread signals
        self.signals.frame_ready.connect(self.detector_widget.update_frame)
        self.signals.log_message.connect(self.log_widget.add_message)
        self.signals.scan_completed.connect(self.on_scan_completed)
        self.signals.scan_failed.connect(self.on_scan_failed)

    def start_scanner_init(self):
        """Start scanner initialization in background thread."""
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
        self.log_widget.log_success(f"Scanner initialized with {led_count} LEDs")

        # Create detector update queue
        detector_update_queue = self.scanner.create_detector_update_queue()

        # Start status monitor thread
        self.monitor_thread = StatusMonitorThread(
            self.signals, self.frame_queue, detector_update_queue
        )
        self.monitor_thread.start()

        # Enable controls now that scanner is ready
        self.control_panel.start_button.setEnabled(True)
        self.statusBar().showMessage("Scanner ready")

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
        # For Phase 1, we'll just log this - proper stop implementation
        # requires additional scanner modifications
        self.log_widget.log_warning("Stop requested (scan will complete current LED)")
        self.statusBar().showMessage("Stop requested...")

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

    def closeEvent(self, event):
        """Handle window close event - clean up scanner and threads."""
        # Stop initialization thread if still running
        if self.init_thread is not None and self.init_thread.isRunning():
            self.init_thread.wait(2000)  # Wait up to 2 seconds

        # Stop monitor thread
        if self.monitor_thread is not None:
            self.monitor_thread.stop()
            self.monitor_thread.wait(2000)  # Wait up to 2 seconds

        # Close scanner
        if self.scanner is not None:
            try:
                self.log_widget.log_info("Closing scanner...")
                self.scanner.close()
            except Exception as e:
                self.log_widget.log_error(f"Error closing scanner: {str(e)}")

        event.accept()
