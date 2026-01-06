# DO NOT MOVE THIS
# FATAL WEIRD CRASH IF THIS ISN'T IMPORTED FIRST DON'T ASK
from marimapper.sfm_process import SFM

from tqdm import tqdm
from pathlib import Path
from marimapper.unified_detector import UnifiedDetector
from marimapper.unified_coordinator import UnifiedCoordinator
from marimapper.queues import Queue2D, Queue3D, Queue3DInfo, DetectionControlEnum
from multiprocessing import get_logger, set_start_method, get_start_method, Queue
from marimapper.file_tools import get_all_2d_led_maps
from marimapper.utils import get_user_confirmation
from marimapper.visualize_process import VisualiseProcess
from marimapper.led import last_view
from marimapper.file_writer_process import FileWriterProcess
from functools import partial
from typing import Optional, List

# This is to do with an issue with open3d bug in estimate normals
# https://github.com/isl-org/Open3D/issues/1428
# if left to its default fork start method, add_normals in sfm_process will fail
# add_normals is also in the wrong file, it should be in sfm.py, but this causes a dependancy crash
# I think there is something very wrong with open3d.geometry.PointCloud.estimate_normals()
# See https://github.com/TheMariday/marimapper/issues/46
# I would prefer not to call this here as it means that any process being called after this will have a different
# spawn method, however it makes tests more robust in isolation
# This is only an issue on Linux, as on Windows and Mac, the default start method is spawn

logger = get_logger()


def join_with_warning(process_to_join, process_name, timeout=10):
    logger.debug(f"{process_name} stopping...")
    process_to_join.join(
        timeout=timeout
    )  # Strangely the return code for join does not match the exitcode attribute

    if process_to_join.exitcode is None:
        logger.warning(f"{process_name} failed to stop gracefully after {timeout}s, forcing termination")
        process_to_join.terminate()  # Force kill the process
        process_to_join.join(timeout=2)  # Wait briefly for termination
        if process_to_join.exitcode is None:
            logger.error(f"{process_name} could not be terminated, killing")
            process_to_join.kill()  # Nuclear option
        return
    if process_to_join.exitcode != 0:
        logger.warning(
            f"{process_name} failed to stop with exit code {process_to_join.exitcode}, some data might be lost"
        )
        return

    logger.debug(f"{process_name} stopped")


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
        interpolation_max_fill: int,
        interpolation_max_error: float,
        check_movement: bool,
        camera_model_name: str,
        axis_config: Optional[dict] = None,
        axis_configs: Optional[List[dict]] = None,
        camera_configs: Optional[List] = None,  # List[CameraConfig] from camera_config.py
        frame_queue=None,
    ):
        """
        Initialize Scanner with unified architecture.

        Args:
            axis_config: Single camera config (for backwards compatibility)
            axis_configs: Multiple camera configs (for multi-camera mode)
            camera_configs: List of CameraConfig objects (new method via JSON config file)
        """
        logger.debug("initialising scanner with unified architecture")
        # VERY important, see top of file
        # Only set if not already set (GUI may have already set it)
        if get_start_method(allow_none=True) != "spawn":
            set_start_method("spawn")

        # Store common parameters
        self.output_dir = output_dir
        self.device = device
        self.exposure = exposure
        self.threshold = threshold
        self.backend_factory = backend_factory
        self.led_start = led_start
        self.led_end = led_end
        self.check_movement = check_movement

        # Determine camera configurations (normalize to list)
        # Priority: camera_configs (new) > axis_configs > axis_config > device
        self.using_new_config = False
        if camera_configs is not None and len(camera_configs) > 0:
            # New method: CameraConfig objects
            self.camera_configs = camera_configs
            self.using_new_config = True
        elif axis_configs is not None and len(axis_configs) > 0:
            self.camera_configs = axis_configs
        elif axis_config is not None:
            self.camera_configs = [axis_config]
        else:
            # USB camera (single)
            self.camera_configs = [{"device": device}]

        self.num_cameras = len(self.camera_configs)
        logger.info(f"Initializing scanner with {self.num_cameras} camera(s)")

        # Initialize common components
        self.file_writer = FileWriterProcess(self.output_dir)
        existing_leds = get_all_2d_led_maps(self.output_dir)
        led_count = led_end - led_start

        self.sfm = SFM(
            interpolation_max_fill,
            interpolation_max_error,
            existing_leds,
            led_count,
            camera_model_name=camera_model_name,
            camera_fov=60,
        )

        self.current_view = last_view(existing_leds) + 1
        self.renderer3d = VisualiseProcess()
        self.detector_update_queue = Queue2D()
        self.gui_3d_info_queue = Queue3DInfo()
        self.gui_3d_data_queue = Queue3D()

        # Connect SFM outputs
        self.sfm.add_output_queue(self.renderer3d.get_input_queue())
        self.sfm.add_output_queue(self.file_writer.get_3d_input_queue())
        self.sfm.add_output_queue(self.gui_3d_data_queue)
        self.sfm.add_output_info_queue(self.gui_3d_info_queue)

        # Create coordinator (always, even for single camera)
        self.coordinator = UnifiedCoordinator(
            backend_factory=backend_factory,
            num_detectors=self.num_cameras,
            led_start=led_start,
            led_end=led_end,
            check_movement=check_movement,
            detection_timeout=1.5,
            led_stabilization_delay=0.05,
        )

        # Connect coordinator to output queues
        self.coordinator.add_output_queue(self.detector_update_queue)

        # Create detectors (one per camera)
        self.detectors = []
        self.detector_frame_queues = []  # For GUI

        for camera_id, cam_config in enumerate(self.camera_configs):
            view_id = self.current_view + camera_id

            # Create frame queue for GUI (if GUI is active)
            detector_frame_queue = None
            if frame_queue is not None:
                detector_frame_queue = Queue(maxsize=3)
                self.detector_frame_queues.append(detector_frame_queue)

            # Determine device and axis_config for this camera
            if self.using_new_config:
                # CameraConfig object - will be passed directly to detector
                cam_device = None
                cam_axis_config = None
                cam_camera_config = cam_config
            else:
                # Legacy dict config
                cam_device = cam_config.get("device", device)
                cam_axis_config = cam_config if "host" in cam_config else None
                cam_camera_config = None

            detector = UnifiedDetector(
                camera_id=camera_id,
                view_id=view_id,
                device=cam_device,
                dark_exposure=exposure,
                threshold=threshold,
                command_queue=self.coordinator.get_command_queue(camera_id),
                result_queue=self.coordinator.get_result_queue(),
                display=True,
                axis_config=cam_axis_config,
                camera_config=cam_camera_config,
                frame_queue=detector_frame_queue,
                detection_timeout=1.5,
            )

            # Connect detector outputs
            detector.add_output_queue(self.sfm.get_input_queue())
            detector.add_output_queue(self.file_writer.get_2d_input_queue())

            self.detectors.append(detector)

        # Start processes
        self.sfm.start()
        self.renderer3d.start()
        self.file_writer.start()
        self.coordinator.start()
        for detector in self.detectors:
            detector.start()

        # Get LED count from coordinator
        self.led_count = self.coordinator.get_led_count()
        self.led_id_range = range(
            self.led_start, min(self.led_end + 1, self.led_count)
        )

        logger.info(
            f"Scanner initialized: {self.num_cameras} camera(s), "
            f"view IDs {self.current_view} to {self.current_view + self.num_cameras - 1}"
        )
        logger.debug("scanner initialised")


    def check_for_crash(self):
        """Check if any critical process has crashed."""
        if not self.coordinator.is_alive():
            raise Exception("Coordinator has stopped unexpectedly")

        for i, detector in enumerate(self.detectors):
            if not detector.is_alive():
                raise Exception(f"Detector {i} has stopped unexpectedly")

        if not self.sfm.is_alive():
            raise Exception("SFM has stopped unexpectedly")

        if not self.renderer3d.is_alive():
            raise Exception("Visualiser has stopped unexpectedly")

        if not self.file_writer.is_alive():
            raise Exception("File writer has stopped unexpectedly")

    def create_detector_update_queue(self):
        """Return the detector update queue for GUI monitoring."""
        return self.detector_update_queue

    def get_3d_info_queue(self):
        """Return the 3D info queue for GUI status table."""
        return self.gui_3d_info_queue

    def get_3d_data_queue(self):
        """Return the 3D data queue for GUI 3D visualization."""
        return self.gui_3d_data_queue

    def get_detector_command_queue(self, detector_index: int = 0):
        """
        Return the command queue for a specific detector.

        Args:
            detector_index: Index of the detector (0, 1, 2, ...)

        Returns:
            Queue for sending commands to the specified detector
        """
        if detector_index >= self.num_cameras:
            logger.error(f"Detector index {detector_index} out of range (have {self.num_cameras} detectors)")
            return None

        try:
            return self.coordinator.get_command_queue(detector_index)
        except Exception as e:
            logger.error(f"Failed to get command queue for detector {detector_index}: {e}")
            return None

    def get_detector_frame_queue(self, detector_index: int = 0):
        """
        Get frame queue for specific detector.

        Args:
            detector_index: Index of the detector (0, 1, 2, ...)

        Returns:
            Queue for receiving frames from the specified detector, or None if not available
        """
        if detector_index >= len(self.detector_frame_queues):
            return None
        return self.detector_frame_queues[detector_index]

    def get_camera_command_queue(self):
        """
        Get the LED control queue for direct LED control (GUI).

        This queue accepts commands for controlling LEDs directly:
        - ("ALL_ON",) - Turn on all LEDs
        - ("ALL_OFF",) - Turn off all LEDs
        - ("SET_LED", led_id, state) - Turn on/off specific LED
        - ("SET_LEDS_BULK", [(led_id, state), ...]) - Bulk LED control

        Returns:
            Queue for sending LED control commands to the coordinator
        """
        return self.coordinator.get_led_control_queue()

    def close(self):
        """Shutdown all scanner processes."""
        logger.debug("scanner closing")

        # Stop coordinator and detectors
        self.coordinator.stop()

        # Signal common processes to stop
        self.sfm.stop()
        self.renderer3d.stop()
        self.file_writer.stop()

        # Join processes
        join_with_warning(self.coordinator, "coordinator", timeout=3)
        for i, detector in enumerate(self.detectors):
            join_with_warning(detector, f"detector_{i}", timeout=3)
        join_with_warning(self.sfm, "SFM", timeout=3)
        join_with_warning(self.file_writer, "File Writer", timeout=3)
        join_with_warning(self.renderer3d, "Visualiser", timeout=3)

        logger.debug("scanner closed")

    def wait_for_scan(self):

        with tqdm(
            total=self.led_id_range.stop - self.led_id_range.start,
            unit="LEDs",
            desc="Capturing sequence",
            smoothing=0,
        ) as progress_bar:

            while True:

                control, data = self.detector_update_queue.get()

                if control == DetectionControlEnum.FAIL:
                    if data:
                        logger.error(f"Scan failed: {data}")
                    else:
                        logger.error("Scan failed")
                    return False

                if control in [DetectionControlEnum.DETECT, DetectionControlEnum.SKIP]:
                    progress_bar.update(1)
                    progress_bar.refresh()

                if control == DetectionControlEnum.DONE:
                    done_view = data
                    logger.info(f"Scan complete {done_view}")
                    return True

                if control == DetectionControlEnum.DELETE:
                    view_id = data
                    logger.info(f"Deleting scan {view_id}")
                    return False

    def mainloop(self):
        """Main loop for CLI mode - repeatedly request scans from user."""
        while True:
            start_scan = get_user_confirmation("Start scan? [y/n]: ")

            if not start_scan:
                print("Exiting Marimapper, please wait")
                return

            self.check_for_crash()

            if len(self.led_id_range) == 0:
                print("LED range is zero, are you using a dummy backend?")
                continue

            # Request scan from coordinator (works for any number of cameras)
            logger.info(f"Starting scan with {self.num_cameras} camera(s)...")
            self.coordinator.request_scan(
                self.led_id_range.start,
                self.led_id_range.stop,
                self.current_view
            )

            # Wait for scan completion
            success = self.wait_for_scan()

            if success:
                # Increment view counter by number of cameras
                self.current_view += self.num_cameras
                logger.info(f"Scan complete! Next view ID: {self.current_view}")
