"""
Main window for MariMapper GUI.

This is the primary window that integrates all GUI components and manages
the Scanner instance.
"""

from multiprocessing import Queue
from pathlib import Path
import csv
import cv2
import json
import numpy as np
from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QMessageBox,
    QTabWidget,
    QPushButton,
)
from PyQt6.QtCore import Qt, pyqtSlot, QTimer, QThread, pyqtSignal

from marimapper.scanner import Scanner
from marimapper.detector_process import CameraCommand
from marimapper.gui.signals import MariMapperSignals
from marimapper.file_tools import load_3d_leds_from_file
from marimapper.gui.widgets.detector_widget import DetectorWidget
from marimapper.gui.widgets.multi_camera_widget import MultiCameraWidget
from marimapper.gui.widgets.control_panel import ControlPanel
from marimapper.gui.widgets.log_widget import LogWidget
from marimapper.gui.widgets.status_table import StatusTable
from marimapper.gui.widgets.visualizer_3d_widget import Visualizer3DWidget
from marimapper.gui.widgets.transform_controls import TransformControlsWidget
from marimapper.gui.widgets.placement_panel import PlacementPanel
from marimapper.gui.worker import StatusMonitorThread
from marimapper.gui.project_manager import ProjectManager
from marimapper.gui.dialogs import NewProjectDialog, OpenProjectDialog
from marimapper.gui.utils import get_backend_type_from_args


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
                axis_configs=self.scanner_args.axis_configs,
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
        self.placement_mode_active = False
        self.placement_selection: set[int] = set()
        self.problem_ids: list[int] = []
        self._pre_placement_layout = None
        self.leds_3d_data = []
        self.current_view_id = 0
        self.is_video_maximized = False

        # Mask management (per-camera)
        self.current_masks = {}  # {camera_index: numpy_array}
        self.mask_resolutions = {}  # {camera_index: (height, width)}
        self.active_camera_index = 0  # Currently displayed camera for mask editing
        self.camera_count = 1  # Number of cameras (1 for single, N for multi)
        self.multi_camera_widget = None  # Created later if multi-camera mode

        # Project management
        self.project_manager = ProjectManager()

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
        self.tab_widget.currentChanged.connect(self.on_tab_changed)
        self.visualizer_3d_widget.key_pressed.connect(self.on_visualizer_key)

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

        # Transform controls (shown only on 3D view)
        self.transform_controls = TransformControlsWidget()
        self.transform_controls.setVisible(False)
        right_layout.addWidget(self.transform_controls)

        self.placement_toggle_btn = QPushButton("Enter Placement Mode")
        self.placement_toggle_btn.setCheckable(True)
        self.placement_toggle_btn.clicked.connect(self.toggle_placement_mode)
        self.placement_toggle_btn.setVisible(False)
        right_layout.addWidget(self.placement_toggle_btn)

        self.placement_panel = PlacementPanel()
        self.placement_panel.setVisible(False)
        self.placement_panel.exit_requested.connect(self.exit_placement_mode)
        self.placement_panel.commit_requested.connect(self.on_placement_commit)
        self.placement_panel.discard_requested.connect(self.on_placement_discard)
        self.placement_panel.problem_selected.connect(self._on_problem_selected)
        self.placement_panel.next_problem_requested.connect(self._on_next_problem_requested)
        self.placement_panel.place_problem_requested.connect(self._on_place_problem_requested)
        self.placement_panel.interpolate_requested.connect(self._on_interpolate_problem_leds)
        right_layout.addWidget(self.placement_panel)

        # LED status table
        self.status_table = StatusTable()
        right_layout.addWidget(self.status_table)

        # Give the status table most of the vertical space
        right_layout.setStretch(0, 1)
        right_layout.setStretch(1, 1)
        right_layout.setStretch(2, 0)
        right_layout.setStretch(3, 0)
        right_layout.setStretch(4, 3)

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

        # Project submenu
        project_menu = file_menu.addMenu("&Project")

        new_project_action = project_menu.addAction("&New Project...")
        new_project_action.triggered.connect(self.on_new_project)

        open_project_action = project_menu.addAction("&Open Project...")
        open_project_action.triggered.connect(self.on_open_project)

        self.close_project_action = project_menu.addAction("&Close Project")
        self.close_project_action.triggered.connect(self.on_close_project)
        self.close_project_action.setEnabled(False)  # Initially disabled

        project_menu.addSeparator()

        delete_project_action = project_menu.addAction("&Delete Project...")
        delete_project_action.triggered.connect(self.on_delete_project)

        file_menu.addSeparator()

        exit_action = file_menu.addAction("E&xit")
        exit_action.triggered.connect(self.close)

        # Help menu
        help_menu = menubar.addMenu("&Help")
        about_action = help_menu.addAction("&About")
        about_action.triggered.connect(self.show_about)

        # Status bar
        self.statusBar().showMessage("Initializing...")

        # Project status label (permanent widget in status bar)
        from PyQt6.QtWidgets import QLabel
        self.project_label = QLabel("No project loaded")
        self.statusBar().addPermanentWidget(self.project_label)

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

        # Control panel <> status table state
        self.control_panel.all_off_requested.connect(self.status_table.set_all_off_state)
        self.control_panel.all_on_requested.connect(self.status_table.set_all_on_state)

        # Detector widget and mask controls
        self.detector_widget.maximize_toggled.connect(self.toggle_video_maximize)
        self.control_panel.paint_mode_toggled.connect(self.detector_widget.set_painting_mode)
        self.control_panel.brush_size_changed.connect(self.detector_widget.set_brush_size)
        self.control_panel.mask_visibility_toggled.connect(self.detector_widget.set_mask_visibility)
        self.control_panel.mask_clear_requested.connect(self.on_clear_mask)
        self.control_panel.mask_save_requested.connect(self.on_save_mask)
        self.control_panel.mask_load_requested.connect(self.on_load_mask)
        self.control_panel.camera_selected.connect(self.on_camera_selected)
        self.detector_widget.mask_updated.connect(self.on_mask_updated)

        # Worker thread signals
        self.signals.frame_ready.connect(self.detector_widget.update_frame)
        self.signals.frame_ready_multi.connect(self.on_frame_ready_multi)
        self.signals.log_message.connect(self.log_widget.add_message)
        self.signals.scan_completed.connect(self.on_scan_completed)
        self.signals.scan_failed.connect(self.on_scan_failed)
        self.signals.reconstruction_updated.connect(self.on_reconstruction_updated)
        self.signals.points_3d_updated.connect(self.on_points_3d_updated)
        self.visualizer_3d_widget.led_clicked.connect(self.on_visualizer_led_clicked)
        self.visualizer_3d_widget.working_positions_changed.connect(self._on_working_positions_changed)

        # Transform controls
        self.transform_controls.transform_changed.connect(self.visualizer_3d_widget.set_transform)
        self.transform_controls.transform_changed.connect(self.on_transform_changed)
        self.transform_controls.save_requested.connect(self.save_transformed_cloud)

    def on_tab_changed(self, index: int):
        """Swap control widgets when entering/exiting 3D view."""
        is_3d = self.tab_widget.tabText(index) == "3D View"
        self.control_panel.setVisible(not is_3d)
        self.transform_controls.setVisible(is_3d and not self.placement_mode_active)
        self.placement_toggle_btn.setVisible(is_3d)
        if not is_3d and self.placement_mode_active:
            if not self.exit_placement_mode(allow_prompt=True):
                # Revert tab back to 3D if user cancels exit
                idx = self.tab_widget.indexOf(self.visualizer_3d_widget)
                if idx >= 0:
                    self.tab_widget.blockSignals(True)
                    self.tab_widget.setCurrentIndex(idx)
                    self.tab_widget.blockSignals(False)

    @pyqtSlot()
    def toggle_placement_mode(self):
        if self.placement_mode_active:
            self.exit_placement_mode(allow_prompt=True)
        else:
            self.enter_placement_mode()

    def enter_placement_mode(self):
        """Switch UI into placement-focused layout."""
        if self.placement_mode_active:
            return

        # Ensure 3D tab is active
        idx = self.tab_widget.indexOf(self.visualizer_3d_widget)
        if idx >= 0:
            self.tab_widget.setCurrentIndex(idx)

        self.placement_mode_active = True
        self.placement_selection.clear()
        self._pre_placement_layout = {
            "main_sizes": self.main_splitter.sizes(),
            "left_sizes": self.left_splitter.sizes(),
            "log_visible": self.log_widget.isVisible(),
            "status_visible": self.status_table.isVisible(),
        }

        self.log_widget.setVisible(False)
        self.status_table.setVisible(False)
        self.transform_controls.setVisible(False)
        self.placement_panel.setVisible(True)
        self.placement_panel.set_dirty(False)
        self.placement_panel.set_selected_led(None)
        self.placement_toggle_btn.blockSignals(True)
        self.placement_toggle_btn.setChecked(True)
        self.placement_toggle_btn.blockSignals(False)
        self.placement_toggle_btn.setText("Exit Placement Mode")
        self.visualizer_3d_widget.set_gizmo_enabled(True)
        self._refresh_problem_list()

        # Bias space toward the 3D viewport
        self.left_splitter.setSizes([max(self.width() - 200, 800), 0])
        self.main_splitter.setSizes([max(self.width() - 250, 900), 250])

        self.visualizer_3d_widget.set_hint_text(
            "Placement: click to select, drag to orbit, right-drag to pan, WASD/Arrows move, Q/E up/down, Esc exits."
        )
        self.visualizer_3d_widget.view.setFocus()
        self.statusBar().showMessage("Placement mode active")

    def exit_placement_mode(self, allow_prompt: bool = True):
        """Restore standard layout and interactions."""
        if not self.placement_mode_active:
            return True
        if allow_prompt and self.placement_panel.is_dirty():
            resp = QMessageBox.question(
                self,
                "Discard placement changes?",
                "You have unsaved placement edits. Exit and discard them?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if resp != QMessageBox.StandardButton.Yes:
                return False
        self.placement_mode_active = False

        self.log_widget.setVisible(self._pre_placement_layout.get("log_visible", True) if self._pre_placement_layout else True)
        self.status_table.setVisible(self._pre_placement_layout.get("status_visible", True) if self._pre_placement_layout else True)
        self.placement_panel.setVisible(False)
        self.transform_controls.setVisible(self.tab_widget.currentWidget() == self.visualizer_3d_widget)
        self.placement_toggle_btn.blockSignals(True)
        self.placement_toggle_btn.setChecked(False)
        self.placement_toggle_btn.blockSignals(False)
        self.placement_toggle_btn.setText("Enter Placement Mode")
        self.visualizer_3d_widget.set_gizmo_enabled(False)

        if self._pre_placement_layout:
            try:
                self.main_splitter.setSizes(self._pre_placement_layout.get("main_sizes", self.main_splitter.sizes()))
                self.left_splitter.setSizes(self._pre_placement_layout.get("left_sizes", self.left_splitter.sizes()))
            except Exception:
                pass
        self._pre_placement_layout = None

        # Restore active LED highlighting from status table and clear placement hint
        try:
            self.visualizer_3d_widget.set_active_leds(self.status_table.manual_on_leds)
        except Exception:
            pass
        self.visualizer_3d_widget.set_hint_text(None)
        # If we exited while dirty (with user confirmation), discard placement edits
        if allow_prompt and self.placement_panel.is_dirty():
            self.on_placement_discard()
        self._clear_placement_selection()
        self.statusBar().showMessage("Placement mode exited")
        return True

    def keyPressEvent(self, event):
        """Handle global shortcuts (e.g., Esc to exit placement)."""
        if event.key() == Qt.Key.Key_Escape and self.placement_mode_active:
            self._clear_placement_selection()
            event.accept()
            return
        if self.placement_mode_active and event.key() == Qt.Key.Key_Tab:
            forward = not bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            if self._select_next_problem(forward):
                event.accept()
                return
        if self.placement_mode_active and self._handle_placement_nudge(event):
            event.accept()
            return
        super().keyPressEvent(event)

    @pyqtSlot(object)
    def on_visualizer_key(self, event):
        """React to key presses that hit the 3D view (for placement nudges)."""
        if self.placement_mode_active and event.key() == Qt.Key.Key_Tab:
            forward = not bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            if self._select_next_problem(forward):
                event.accept()
                return
        if self.placement_mode_active and event.key() == Qt.Key.Key_Escape:
            self._clear_placement_selection()
            event.accept()
            return
        if self.placement_mode_active and self._handle_placement_nudge(event):
            event.accept()
            return

    def _update_placement_selection_display(self):
        """Refresh selection summary in placement panel."""
        if not self.placement_mode_active:
            return
        if not self.placement_selection:
            self.placement_panel.set_selected_led(None)
            self.placement_panel.select_problem_id(None)
            return
        led_id = next(iter(self.placement_selection))
        pos = None
        exported = self.visualizer_3d_widget.export_transformed_leds()
        if exported:
            ids, positions, _, _ = exported
            try:
                idx = ids.index(led_id)
                pos = tuple(positions[idx])
            except ValueError:
                pos = None
        self.placement_panel.set_selected_led(led_id, pos)
        self.placement_panel.select_problem_id(led_id if led_id in self.problem_ids else None)

    @pyqtSlot()
    def on_placement_commit(self):
        """Placeholder commit hook; persists working positions in future sprint."""
        self.save_transformed_cloud()
        self.placement_panel.set_dirty(False)
        self.statusBar().showMessage("Placement committed")
        self._prune_solved_problems()


    @pyqtSlot()
    def on_placement_discard(self):
        """Reset working positions to originals."""
        try:
            self.visualizer_3d_widget.reset_working_positions()
        except Exception:
            pass
        self.placement_panel.set_dirty(False)
        self._update_placement_selection_display()
        self.statusBar().showMessage("Placement changes discarded (reset to original)")
        self.visualizer_3d_widget.set_selection_ids(self.placement_selection if self.placement_mode_active else None)

    @pyqtSlot(dict)
    def on_reconstruction_updated(self, led_info_dict):
        """Update status table and problem list when reconstruction changes."""
        self.status_table.update_led_info(led_info_dict)
        self._refresh_problem_list()

    @pyqtSlot(list)
    def on_points_3d_updated(self, leds_3d):
        """Store 3D data and forward to visualizer."""
        try:
            self.leds_3d_data = list(leds_3d)
        except Exception:
            self.leds_3d_data = []
        self.visualizer_3d_widget.update_3d_data(leds_3d)

    def _handle_placement_nudge(self, event) -> bool:
        """Keyboard nudges in placement mode (WASD/Arrows for X/Z, Q/E for Y)."""
        if not self.placement_selection:
            return False
        key = event.key()
        step = 0.02
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            step *= 5  # coarse move
        dx = dy = dz = 0.0
        if key in (Qt.Key.Key_W, Qt.Key.Key_Up):
            dz += step
        elif key in (Qt.Key.Key_S, Qt.Key.Key_Down):
            dz -= step
        elif key in (Qt.Key.Key_A, Qt.Key.Key_Left):
            dx += step
        elif key in (Qt.Key.Key_D, Qt.Key.Key_Right):
            dx -= step
        elif key == Qt.Key.Key_E:
            dy += step
        elif key == Qt.Key.Key_Q:
            dy -= step
        else:
            return False

        moved = self.visualizer_3d_widget.nudge_working_leds(self.placement_selection, (dx, dy, dz))
        if moved:
            self.placement_panel.set_dirty(True)
            self._update_placement_selection_display()
            self.visualizer_3d_widget.set_selection_ids(self.placement_selection)
        return moved

    def _refresh_problem_list(self):
        """Refresh the problem list in placement panel based on status table data."""
        try:
            ids = self.status_table.get_problem_led_ids()
        except Exception:
            ids = []
        self.problem_ids = ids
        if self.placement_mode_active:
            self.placement_panel.set_problem_ids(ids)
            # keep selection highlight consistent
            if self.placement_selection:
                current = next(iter(self.placement_selection))
                self.placement_panel.select_problem_id(current if current in ids else None)

    @pyqtSlot(int)
    def _on_problem_selected(self, led_id: int):
        """Select a problem LED from the list."""
        if not self.placement_mode_active:
            return
        self._set_placement_selection(led_id)

    @pyqtSlot(bool)
    def _on_next_problem_requested(self, forward: bool):
        self._select_next_problem(forward)

    @pyqtSlot(int)
    def _on_place_problem_requested(self, led_id: int):
        """Focus selection on a problem LED (same as selecting it)."""
        self._ensure_problem_placeholder(led_id)
        self._set_placement_selection(led_id)

    def _select_next_problem(self, forward: bool = True) -> bool:
        """Select next/previous problem LED. Returns True if selection changed."""
        if not self.problem_ids:
            return False
        if not self.placement_selection:
            target = self.problem_ids[0] if forward else self.problem_ids[-1]
        else:
            current = next(iter(self.placement_selection))
            if current in self.problem_ids:
                idx = self.problem_ids.index(current)
                idx = (idx + (1 if forward else -1)) % len(self.problem_ids)
                target = self.problem_ids[idx]
            else:
                target = self.problem_ids[0] if forward else self.problem_ids[-1]
        self._set_placement_selection(target)
        return True

    def _set_placement_selection(self, led_id: int | None):
        """Helper to update placement selection, visuals, and gizmo anchor."""
        if led_id is None:
            self.placement_selection = set()
        else:
            self.placement_selection = {led_id}
        self.visualizer_3d_widget.set_active_leds(self.placement_selection)
        self.visualizer_3d_widget.set_selection_ids(self.placement_selection)
        self._update_placement_selection_display()

    def _clear_placement_selection(self):
        """Deselect current placement selection and hide gizmo anchor."""
        self.placement_selection = set()
        self.visualizer_3d_widget.set_active_leds(set())
        self.visualizer_3d_widget.set_selection_ids(set())
        self._update_placement_selection_display()

    def _ensure_problem_placeholder(self, led_id: int):
        """If a problem LED lacks a 3D point, seed it near neighbors so it can be placed."""
        if led_id in self.visualizer_3d_widget.id_to_index:
            return
        guess = self._guess_position_for_led(led_id)
        if guess is not None:
            self.visualizer_3d_widget.add_placeholder_led(led_id, guess)

    def _guess_position_for_led(self, led_id: int):
        """Guess an initial position using nearby known LEDs by ID; fallback to centroid."""
        export = self.visualizer_3d_widget.export_working_leds()
        if not export:
            return np.array([0.0, 0.0, 0.0], dtype=float)
        ids, positions, _, _ = export
        if not ids or len(ids) == 0:
            return np.array([0.0, 0.0, 0.0], dtype=float)
        id_pos = list(zip(ids, positions))
        id_pos = [ip for ip in id_pos if ip[1] is not None]
        # Sort by absolute ID distance
        id_pos.sort(key=lambda ip: abs(ip[0] - led_id))
        if id_pos:
            nearest = id_pos[:2]
            pts = np.array([p for _, p in nearest], dtype=float)
            return np.mean(pts, axis=0)
        return np.mean(np.array(positions, dtype=float), axis=0)

    @pyqtSlot()
    def _on_interpolate_problem_leds(self):
        """Linearly interpolate problem LEDs between known anchors."""
        if not self.problem_ids:
            self.log_widget.log_info("No problem LEDs to interpolate.")
            return
        export = self.visualizer_3d_widget.export_working_leds()
        if not export:
            self.log_widget.log_warning("No 3D data available for interpolation.")
            return
        ids, positions, _, _ = export
        if not ids:
            self.log_widget.log_warning("No 3D data available for interpolation.")
            return

        id_to_idx = dict(zip(ids, range(len(ids))))
        positions = np.array(positions, copy=True, dtype=float)

        # Anchors: non-problem IDs with finite positions
        anchors = [(i, positions[id_to_idx[i]]) for i in ids if i not in self.problem_ids and i in id_to_idx]
        anchors = [(idx, pos) for idx, pos in anchors if np.all(np.isfinite(pos))]
        anchors.sort(key=lambda a: a[0])

        if len(anchors) < 2:
            self.log_widget.log_warning("Not enough anchor LEDs to interpolate (need at least 2 non-problem points).")
            return

        # Collect interpolations
        changes = []
        for a, b in zip(anchors[:-1], anchors[1:]):
            idx_a, pos_a = a
            idx_b, pos_b = b
            gap = idx_b - idx_a - 1
            if gap <= 0:
                continue
            for k in range(1, gap + 1):
                target_id = idx_a + k
                if target_id not in self.problem_ids:
                    continue
                t = k / float(gap + 1)
                interp = pos_a + (pos_b - pos_a) * t
                changes.append((target_id, interp))

        if not changes:
            self.log_widget.log_info("No problem LEDs fell between known anchors; nothing interpolated.")
            return

        # Apply changes, inserting placeholders if needed
        for led_id, pos in changes:
            if led_id in id_to_idx:
                positions[id_to_idx[led_id]] = pos
            else:
                # add placeholder LED to visualizer and mapping
                if self.visualizer_3d_widget.add_placeholder_led(led_id, pos):
                    ids = ids + [led_id]
                    positions = np.vstack([positions, pos])
                    id_to_idx[led_id] = len(ids) - 1

        # Ensure working positions updated in visualizer
        self.visualizer_3d_widget.set_working_positions(positions)
        self.placement_panel.set_dirty(True)
        self.log_widget.log_success(f"Interpolated {len(changes)} problem LEDs between known anchors.")

    @pyqtSlot()
    def _on_working_positions_changed(self):
        """Mark placement dirty when working positions change in placement mode."""
        if self.placement_mode_active:
            self.placement_panel.set_dirty(True)

    def _prune_solved_problems(self):
        """Remove any problem IDs that now have positions (e.g., after commit)."""
        export = self.visualizer_3d_widget.export_working_leds()
        if not export:
            return
        ids, positions, _, _ = export
        if ids is None or positions is None:
            return
        solved = []
        for pid in self.problem_ids:
            try:
                idx = ids.index(pid)
                pos = positions[idx]
                if pos is not None and np.all(np.isfinite(pos)):
                    solved.append(pid)
            except ValueError:
                continue
        if not solved:
            return
        self.problem_ids = [pid for pid in self.problem_ids if pid not in solved]
        if self.placement_mode_active:
            self.placement_panel.set_problem_ids(self.problem_ids)

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

        # Detect camera count for multi-camera support (do this early!)
        if hasattr(scanner, "detector_workers") and scanner.detector_workers:
            # Multi-camera mode
            self.camera_count = len(scanner.detector_workers)
            self.log_widget.log_info(f"Multi-camera mode detected: {self.camera_count} cameras")

            # Get worker frame queues for multi-camera
            frame_queues = [
                scanner.get_worker_frame_queue(i)
                for i in range(self.camera_count)
            ]

            # Replace single-camera UI with multi-camera grid
            self._setup_multi_camera_ui()
        else:
            # Single camera mode
            self.camera_count = 1
            self.log_widget.log_info("Single camera mode")
            frame_queues = self.frame_queue  # Single queue

        # Start status monitor thread with appropriate frame queues
        self.monitor_thread = StatusMonitorThread(
            self.signals, frame_queues, detector_update_queue, info_3d_queue, data_3d_queue
        )
        self.monitor_thread.start()

        self.log_widget.log_info("Monitor thread started, watching for 3D info updates...")

        # Log diagnostic information
        if self.camera_count == 1:
            self.log_widget.log_info(f"Detector process alive: {scanner.detector.is_alive()}")
        else:
            alive_workers = sum(1 for w in scanner.detector_workers if w.is_alive())
            self.log_widget.log_info(f"Detector workers alive: {alive_workers}/{self.camera_count}")
        self.log_widget.log_info(f"Frame queue created: {self.frame_queue is not None}")

        # Enable controls now that scanner is ready
        self.control_panel.start_button.setEnabled(True)
        self.statusBar().showMessage("Scanner ready")

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

    def _setup_multi_camera_ui(self):
        """Replace single camera widget with multi-camera grid."""
        # Remove old "Video Feed" tab (index 0)
        self.tab_widget.removeTab(0)

        # Create multi-camera widget
        self.multi_camera_widget = MultiCameraWidget(self.camera_count)
        self.tab_widget.insertTab(0, self.multi_camera_widget, "Camera Grid")

        # Connect signals
        self.multi_camera_widget.camera_selected.connect(self.on_camera_selected)
        self.multi_camera_widget.mask_updated.connect(self.on_mask_updated_multi)

        # Update control panel to show camera selector
        self.control_panel.set_camera_count(self.camera_count)

        # Disable single-camera detector widget
        self.detector_widget.hide()
        self.detector_widget = None

        self.log_widget.log_info(f"Multi-camera UI initialized with {self.camera_count} cameras")

    @pyqtSlot(int, object)
    def on_frame_ready_multi(self, camera_index: int, frame):
        """
        Handle frame from multi-camera mode.

        Args:
            camera_index: Index of camera that produced this frame
            frame: Video frame (numpy array)
        """
        # Route frame to multi-camera grid widget
        if self.multi_camera_widget is not None:
            self.multi_camera_widget.update_frame(camera_index, frame)
        elif camera_index == 0:
            # Fallback: show camera 0 on main detector widget if grid not yet created
            if self.detector_widget is not None:
                self.detector_widget.update_frame(frame)

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
            if self.camera_count == 1:
                # Single camera mode
                from marimapper.detector_process import CameraCommand
                camera_queue = self.scanner.get_camera_command_queue()
                camera_queue.put(CameraCommand.SET_DARK)
                self.log_widget.log_info("Camera set to DARK mode")
            else:
                # Multi-camera mode: broadcast to all workers
                for i in range(self.camera_count):
                    worker_queue = self.scanner.get_worker_command_queue(i)
                    if worker_queue is not None:
                        worker_queue.put(("SET_DARK",))
                self.log_widget.log_info(f"All {self.camera_count} cameras set to DARK mode")

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
            if self.camera_count == 1:
                # Single camera mode
                from marimapper.detector_process import CameraCommand
                camera_queue = self.scanner.get_camera_command_queue()
                camera_queue.put(CameraCommand.SET_BRIGHT)
                self.log_widget.log_info("Camera set to BRIGHT mode")
            else:
                # Multi-camera mode: broadcast to all workers
                for i in range(self.camera_count):
                    worker_queue = self.scanner.get_worker_command_queue(i)
                    if worker_queue is not None:
                        worker_queue.put(("SET_BRIGHT",))
                self.log_widget.log_info(f"All {self.camera_count} cameras set to BRIGHT mode")

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
            if self.camera_count == 1:
                # Single camera mode
                from marimapper.detector_process import CameraCommand
                camera_queue = self.scanner.get_camera_command_queue()
                camera_queue.put((CameraCommand.SET_THRESHOLD, value))
                self.log_widget.log_info(f"Detection threshold set to {value}")
            else:
                # Multi-camera mode: broadcast to all workers
                for i in range(self.camera_count):
                    worker_queue = self.scanner.get_worker_command_queue(i)
                    if worker_queue is not None:
                        worker_queue.put(("SET_THRESHOLD", value))
                self.log_widget.log_info(f"Threshold set to {value} for all {self.camera_count} cameras")

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
        if self.placement_mode_active:
            self.placement_selection = {led_id}
            self.visualizer_3d_widget.set_active_leds(self.placement_selection)
            self.visualizer_3d_widget.set_selection_ids(self.placement_selection)
            self._update_placement_selection_display()
            return
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

    @pyqtSlot()
    def save_transformed_cloud(self):
        """Save the currently displayed (transformed) 3D points to CSV."""
        export = self.visualizer_3d_widget.export_transformed_leds()
        working_export = self.visualizer_3d_widget.export_working_leds()
        if not export:
            self.log_widget.log_warning("No 3D data available to save.")
            return

        ids, positions, normals, errors = export

        # Use project reconstruction folder if active, otherwise current directory
        if self.project_manager.is_project_active():
            reconstruction_dir = self.project_manager.get_reconstruction_dir()
            path = reconstruction_dir / "transformed_led_map_3d.csv"
        else:
            path = Path.cwd() / "transformed_led_map_3d.csv"

        try:
            with open(path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["index", "x", "y", "z", "xn", "yn", "zn", "error"])
                for idx, (pos, nrm, err) in enumerate(zip(positions, normals, errors)):
                    led_idx = ids[idx] if ids else idx
                    writer.writerow(
                        [led_idx, pos[0], pos[1], pos[2], nrm[0], nrm[1], nrm[2], err]
                    )
            self.log_widget.log_success(f"Saved transformed map to {path}")

            # Write base map in un-transformed working space so it stays consistent for reloads
            if working_export:
                base_ids, base_positions, base_normals, base_errors = working_export
                if self.project_manager.is_project_active():
                    base_path = reconstruction_dir / "led_map_3d.csv"
                else:
                    base_path = Path(self.scanner_args.output_dir) / "led_map_3d.csv"
                with open(base_path, "w", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow(["index", "x", "y", "z", "xn", "yn", "zn", "error"])
                    for idx, (pos, nrm, err) in enumerate(zip(base_positions, base_normals, base_errors)):
                        led_idx = base_ids[idx] if base_ids else idx
                        writer.writerow(
                            [led_idx, pos[0], pos[1], pos[2], nrm[0], nrm[1], nrm[2], err]
                        )
                self.log_widget.log_success(f"Updated base map at {base_path}")

            # Save transform to project if active
            if self.project_manager.is_project_active():
                self.project_manager.set_transform(
                    self.visualizer_3d_widget.current_transform
                )

        except Exception as e:
            self.log_widget.log_error(f"Failed to save transformed map: {e}")

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
        if self.detector_widget and self.detector_widget.video_label.pixmap():
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

    @pyqtSlot(int, object)
    def on_mask_updated_multi(self, camera_index: int, mask_numpy):
        """Handle mask update from multi-camera grid."""
        if mask_numpy is None:
            return

        # Store mask
        self.current_masks[camera_index] = mask_numpy

        # Get resolution from the specific camera widget in grid
        if self.multi_camera_widget:
            widget = self.multi_camera_widget.detector_widgets[camera_index]
            if widget.video_label.pixmap():
                pixmap = widget.video_label.pixmap()
                self.mask_resolutions[camera_index] = (
                    pixmap.height(),
                    pixmap.width(),
                )

        # Send to detector worker
        self.send_mask_to_detector(camera_index)

        self.log_widget.log_info(f"Mask updated for camera {camera_index}")

    @pyqtSlot()
    def on_clear_mask(self):
        """Clear the current mask."""
        # Clear mask for active camera
        self.current_masks.pop(self.active_camera_index, None)
        self.mask_resolutions.pop(self.active_camera_index, None)

        # Clear in appropriate widget
        if self.multi_camera_widget:
            self.multi_camera_widget.clear_mask(self.active_camera_index)
        elif self.detector_widget:
            self.detector_widget.set_mask_from_numpy(None)

        # Send clear command to detector
        self.send_mask_to_detector(self.active_camera_index)

        self.log_widget.log_success(
            f"Mask cleared for camera {self.active_camera_index}"
        )

    @pyqtSlot()
    def on_save_mask(self):
        """Save mask to file (session-only, in output_dir)."""
        if self.active_camera_index not in self.current_masks:
            self.log_widget.log_warning("No mask to save")
            return

        try:
            # Masks are session-only - save to output_dir, not project
            masks_dir = Path(self.scanner_args.output_dir)

            # Get mask file path for active camera
            mask_file_path = (
                masks_dir / f"detection_mask_{self.active_camera_index}.png"
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
        """Load mask from file (session-only, from output_dir)."""
        try:
            # Masks are session-only - load from output_dir, not project
            masks_dir = Path(self.scanner_args.output_dir)

            # Get mask file path for active camera
            mask_file_path = (
                masks_dir / f"detection_mask_{self.active_camera_index}.png"
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

        # Update multi-camera widget if in multi-camera mode
        if self.multi_camera_widget:
            self.multi_camera_widget.set_active_camera(camera_index)
            self.log_widget.log_info(f"Camera {camera_index} selected")
        elif self.detector_widget:
            # Single-camera mode: Load that camera's mask into DetectorWidget
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
        """Auto-load saved masks for all cameras on startup (session-only)."""
        # Masks are session-only - only check output_dir, not project
        masks_dir = Path(self.scanner_args.output_dir)

        for camera_index in range(self.camera_count):
            mask_file_path = (
                masks_dir / f"detection_mask_{camera_index}.png"
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
        # Use project reconstruction folder if active, otherwise output_dir
        if self.project_manager.is_project_active():
            reconstruction_dir = self.project_manager.get_reconstruction_dir()
            led_map_3d_path = reconstruction_dir / "led_map_3d.csv"
            transformed_path = reconstruction_dir / "transformed_led_map_3d.csv"
        else:
            led_map_3d_path = Path(self.scanner_args.output_dir) / "led_map_3d.csv"
            transformed_path = Path(self.scanner_args.output_dir) / "transformed_led_map_3d.csv"

        load_path = None
        # Prefer base map; fall back to transformed only if base missing
        if led_map_3d_path.exists():
            load_path = led_map_3d_path
        elif transformed_path.exists():
            load_path = transformed_path

        if load_path is None:
            self.log_widget.log_info("No existing 3D data found")
            return

        try:
            self.log_widget.log_info(f"Loading existing 3D data from {load_path.name}...")
            leds_3d = load_3d_leds_from_file(load_path)

            if leds_3d is not None and len(leds_3d) > 0:
                self.log_widget.log_success(f"Loaded {len(leds_3d)} LEDs from existing 3D map ({load_path.name})")
                # Display in 3D widget
                self.visualizer_3d_widget.update_3d_data(leds_3d)
                # Optionally switch to 3D View tab to show the loaded data
                self.tab_widget.setCurrentIndex(1)  # Switch to 3D View tab
                self.log_widget.log_info("Switched to 3D View tab to display loaded data")
            else:
                self.log_widget.log_warning("3D data file exists but contains no valid data")

        except Exception as e:
            self.log_widget.log_error(f"Failed to load 3D data: {e}")

    # Project Management Methods

    def on_transform_changed(self, transform: dict):
        """Save transform to active project when it changes."""
        if self.project_manager.is_project_active():
            self.project_manager.set_transform(transform)

    def update_project_status(self):
        """Update project status label in status bar."""
        if self.project_manager.is_project_active():
            project = self.project_manager.get_active_project()
            self.project_label.setText(f"Project: {project.config['project_name']}")
            self.close_project_action.setEnabled(True)
        else:
            self.project_label.setText("No project loaded")
            self.close_project_action.setEnabled(False)

    def on_new_project(self):
        """Handle New Project menu action."""
        if not self.scanner:
            QMessageBox.warning(
                self,
                "Scanner Not Ready",
                "Please wait for scanner to initialize before creating a project."
            )
            return

        # Show new project dialog
        dialog = NewProjectDialog(parent=self)

        if dialog.exec() != NewProjectDialog.DialogCode.Accepted:
            return

        # Get project configuration
        name, location, description, copy_settings = dialog.get_project_config()

        try:
            # Get backend type
            backend_type = get_backend_type_from_args(self.scanner_args)

            # Create project
            if copy_settings:
                # Use current scanner settings
                project = self.project_manager.create_project(
                    name, location, self.scanner_args, backend_type, description
                )
            else:
                # Use default settings (current implementation always copies)
                project = self.project_manager.create_project(
                    name, location, self.scanner_args, backend_type, description
                )

            # Set as active project
            self.project_manager.set_active_project(project)

            # Update scanner output directory to project scans folder
            if self.scanner:
                from marimapper.scanner import join_with_warning
                from marimapper.file_writer_process import FileWriterProcess

                # Stop and restart file writer with new output directory
                self.scanner.file_writer.stop()
                join_with_warning(self.scanner.file_writer, "File Writer", timeout=3)

                self.scanner.output_dir = project.get_scans_dir()
                self.scanner.file_writer = FileWriterProcess(project.get_scans_dir())

                # Reconnect queues
                self.scanner.sfm.add_output_queue(
                    self.scanner.file_writer.get_3d_input_queue()
                )

                if hasattr(self.scanner, 'multi_camera_mode') and self.scanner.multi_camera_mode:
                    for worker in self.scanner.detector_workers:
                        worker.add_output_queue(
                            self.scanner.file_writer.get_2d_input_queue()
                        )
                else:
                    self.scanner.detector.add_output_queue(
                        self.scanner.file_writer.get_2d_input_queue()
                    )

                self.scanner.file_writer.start()

            # Update UI
            self.update_project_status()
            self.log_widget.log_success(f"Created and activated project: {name}")

        except FileExistsError as e:
            QMessageBox.critical(self, "Project Creation Failed", str(e))
        except Exception as e:
            QMessageBox.critical(
                self,
                "Project Creation Failed",
                f"An error occurred while creating the project:\n\n{str(e)}"
            )
            self.log_widget.log_error(f"Project creation failed: {e}")

    def on_open_project(self):
        """Handle Open Project menu action."""
        # Show open project dialog
        project_folder = OpenProjectDialog.get_project_folder(
            parent=self,
            start_dir=self.project_manager.projects_root
        )

        if not project_folder:
            return

        try:
            # Load project
            project = self.project_manager.load_project(project_folder)

            # Check backend compatibility
            project_backend = project.config['scanner_config']['backend']['type']
            current_backend = get_backend_type_from_args(self.scanner_args)

            if project_backend != current_backend:
                response = QMessageBox.warning(
                    self,
                    "Backend Mismatch",
                    f"Project uses '{project_backend}' backend but scanner is running "
                    f"'{current_backend}'.\n\n"
                    f"Some features may not work correctly. Continue anyway?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No
                )

                if response != QMessageBox.StandardButton.Yes:
                    return

            # Set as active project
            self.project_manager.set_active_project(project)

            # Update scanner output directory
            if self.scanner:
                from marimapper.scanner import join_with_warning
                from marimapper.file_writer_process import FileWriterProcess

                # Stop and restart file writer with new output directory
                self.scanner.file_writer.stop()
                join_with_warning(self.scanner.file_writer, "File Writer", timeout=3)

                self.scanner.output_dir = project.get_scans_dir()
                self.scanner.file_writer = FileWriterProcess(project.get_scans_dir())

                # Reconnect queues
                self.scanner.sfm.add_output_queue(
                    self.scanner.file_writer.get_3d_input_queue()
                )

                if hasattr(self.scanner, 'multi_camera_mode') and self.scanner.multi_camera_mode:
                    for worker in self.scanner.detector_workers:
                        worker.add_output_queue(
                            self.scanner.file_writer.get_2d_input_queue()
                        )
                else:
                    self.scanner.detector.add_output_queue(
                        self.scanner.file_writer.get_2d_input_queue()
                    )

                self.scanner.file_writer.start()

            # Load project data
            self.load_project_data()

            # Update UI
            self.update_project_status()
            self.log_widget.log_success(f"Opened project: {project.config['project_name']}")

        except (FileNotFoundError, ValueError) as e:
            QMessageBox.critical(self, "Failed to Open Project", str(e))
        except Exception as e:
            QMessageBox.critical(
                self,
                "Failed to Open Project",
                f"An error occurred while opening the project:\n\n{str(e)}"
            )
            self.log_widget.log_error(f"Project load failed: {e}")

    def load_project_data(self):
        """Load all data from active project (2D scans, 3D data, transforms)."""
        if not self.project_manager.is_project_active():
            return

        project = self.project_manager.get_active_project()

        # Note: Masks are not loaded from projects - they are session-only
        # and should be drawn fresh each time

        # Load 2D scans
        leds_2d = self.project_manager.load_all_2d_scans()

        # Load 3D reconstruction
        leds_3d = self.project_manager.load_3d_reconstruction()

        # Reconstruct LED info for Status Table
        if leds_3d or leds_2d:
            led_info_dict = self._reconstruct_led_info(leds_2d, leds_3d)

            # Update Status Table
            if led_info_dict:
                self.status_table.update_led_info(led_info_dict)
                self.log_widget.log_info(f"Loaded status for {len(led_info_dict)} LEDs")

            # Update 3D visualization
            if leds_3d and len(leds_3d) > 0:
                try:
                    self.leds_3d_data = list(leds_3d)
                except Exception:
                    self.leds_3d_data = leds_3d
                self.visualizer_3d_widget.update_3d_data(leds_3d)
                self.tab_widget.setCurrentIndex(1)  # Switch to 3D View
                self.log_widget.log_info(f"Loaded {len(leds_3d)} 3D points from project")

        # Refresh problem list based on latest status data
        self._refresh_problem_list()

        # Load transform
        transform = self.project_manager.get_transform()
        if transform:
            self.visualizer_3d_widget.set_transform(**transform)
            self.transform_controls.set_transform(transform)
            self.log_widget.log_info("Loaded visualization transform from project")

    def _reconstruct_led_info(self, leds_2d, leds_3d):
        """
        Reconstruct LED info dictionary from 2D and 3D data.

        Args:
            leds_2d: List of LED2D objects
            leds_3d: List of LED3D objects (or None)

        Returns:
            Dictionary mapping LED ID to LEDInfo enum
        """
        from marimapper.led import LEDInfo

        led_info_dict = {}

        # Build set of LED IDs that have 3D reconstruction
        reconstructed_ids = set()
        if leds_3d:
            for led_3d in leds_3d:
                led_info_dict[led_3d.led_id] = led_3d.get_info()
                reconstructed_ids.add(led_3d.led_id)

        # Process 2D detections to find DETECTED and UNRECONSTRUCTABLE LEDs
        if leds_2d:
            # Group 2D detections by LED ID
            detections_by_id = {}
            for led_2d in leds_2d:
                if led_2d.led_id not in detections_by_id:
                    detections_by_id[led_2d.led_id] = []
                detections_by_id[led_2d.led_id].append(led_2d)

            # Classify LEDs without 3D reconstruction
            for led_id, detections in detections_by_id.items():
                if led_id not in reconstructed_ids:
                    # LED was detected but not reconstructed
                    if len(detections) >= 2:
                        # Multiple views but failed reconstruction
                        led_info_dict[led_id] = LEDInfo.UNRECONSTRUCTABLE
                    elif len(detections) == 1:
                        # Only detected in one view
                        led_info_dict[led_id] = LEDInfo.DETECTED

        return led_info_dict

    def on_close_project(self):
        """Handle Close Project menu action."""
        if not self.project_manager.is_project_active():
            return

        project_name = self.project_manager.get_active_project().config['project_name']

        # Close project (saves automatically)
        self.project_manager.close_project()

        # Update UI
        self.update_project_status()
        self.log_widget.log_info(f"Closed project: {project_name}")

        # Optionally reset output directory to default
        if self.scanner:
            from marimapper.scanner import join_with_warning
            from marimapper.file_writer_process import FileWriterProcess

            # Stop and restart file writer with default output directory
            self.scanner.file_writer.stop()
            join_with_warning(self.scanner.file_writer, "File Writer", timeout=3)

            self.scanner.output_dir = self.scanner_args.output_dir
            self.scanner.file_writer = FileWriterProcess(self.scanner_args.output_dir)

            # Reconnect queues
            self.scanner.sfm.add_output_queue(
                self.scanner.file_writer.get_3d_input_queue()
            )

            if hasattr(self.scanner, 'multi_camera_mode') and self.scanner.multi_camera_mode:
                for worker in self.scanner.detector_workers:
                    worker.add_output_queue(
                        self.scanner.file_writer.get_2d_input_queue()
                    )
            else:
                self.scanner.detector.add_output_queue(
                    self.scanner.file_writer.get_2d_input_queue()
                )

            self.scanner.file_writer.start()

    def on_delete_project(self):
        """Handle Delete Project menu action."""
        # Show open project dialog to select project to delete
        project_folder = OpenProjectDialog.get_project_folder(
            parent=self,
            start_dir=self.project_manager.projects_root
        )

        if not project_folder:
            return

        try:
            # Load project to get its name
            project = self.project_manager.load_project(project_folder)
            project_name = project.config['project_name']

            # Confirm deletion
            response = QMessageBox.question(
                self,
                "Delete Project?",
                f"This will permanently delete the project folder and all data:\n\n"
                f"{project.base_folder}\n\n"
                f"Project: {project_name}\n\n"
                f"This action cannot be undone. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )

            if response != QMessageBox.StandardButton.Yes:
                return

            # Delete project
            self.project_manager.delete_project(project)

            # Update UI
            self.update_project_status()
            self.log_widget.log_success(f"Deleted project: {project_name}")

        except Exception as e:
            QMessageBox.critical(
                self,
                "Failed to Delete Project",
                f"An error occurred while deleting the project:\n\n{str(e)}"
            )
            self.log_widget.log_error(f"Project deletion failed: {e}")

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
