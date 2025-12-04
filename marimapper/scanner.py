# DO NOT MOVE THIS
# FATAL WEIRD CRASH IF THIS ISN'T IMPORTED FIRST DON'T ASK
from marimapper.sfm_process import SFM

from tqdm import tqdm
from pathlib import Path
from marimapper.detector_process import DetectorProcess
from marimapper.coordinator_process import CoordinatorProcess
from marimapper.detector_worker_process import DetectorWorkerProcess
from marimapper.queues import Queue2D, Queue3DInfo, DetectionControlEnum
from multiprocessing import get_logger, set_start_method, get_start_method
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
        frame_queue=None,
    ):
        """
        Initialize Scanner for single or multi-camera mode.

        Args:
            axis_config: Single camera config (for backwards compatibility)
            axis_configs: Multiple camera configs (for multi-camera mode)
                         If provided with len > 1, enables multi-camera mode
        """
        logger.debug("initialising scanner")
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
        self.frame_queue = frame_queue

        # Determine mode: multi-camera or single-camera
        self.multi_camera_mode = axis_configs is not None and len(axis_configs) > 1

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

        # Connect SFM outputs
        self.sfm.add_output_queue(self.renderer3d.get_input_queue())
        self.sfm.add_output_queue(self.file_writer.get_3d_input_queue())
        self.sfm.add_output_info_queue(self.gui_3d_info_queue)

        # Initialize mode-specific components
        if self.multi_camera_mode:
            logger.info(f"Initializing multi-camera mode with {len(axis_configs)} cameras")
            self._init_multi_camera(axis_configs)
        else:
            logger.info("Initializing single-camera mode")
            self._init_single_camera(axis_config)

        logger.debug("scanner initialised")

    def _init_single_camera(self, axis_config: Optional[dict]):
        """Initialize single-camera mode (existing behavior)."""
        self.detector = DetectorProcess(
            device=self.device,
            dark_exposure=self.exposure,
            threshold=self.threshold,
            backend_factory=self.backend_factory,
            display=True,
            check_movement=self.check_movement,
            axis_config=axis_config,
            frame_queue=self.frame_queue,
        )

        # Connect detector outputs
        self.detector.add_output_queue(self.sfm.get_input_queue())
        self.detector.add_output_queue(self.detector_update_queue)
        self.detector.add_output_queue(self.file_writer.get_2d_input_queue())

        # Connect SFM to detector (for LED colorization)
        self.sfm.add_output_info_queue(self.detector.get_input_3d_info_queue())

        # Start processes
        self.sfm.start()
        self.renderer3d.start()
        self.detector.start()
        self.file_writer.start()

        # Get LED count
        self.led_count = self.detector.get_led_count()
        self.led_id_range = range(
            self.led_start, min(self.led_end + 1, self.led_count)
        )

        # Placeholder attributes for compatibility
        self.coordinator = None
        self.detector_workers = None

    def _init_multi_camera(self, axis_configs: List[dict]):
        """Initialize multi-camera mode with coordinator and workers."""
        num_cameras = len(axis_configs)

        # Create coordinator
        self.coordinator = CoordinatorProcess(
            backend_factory=self.backend_factory,
            num_cameras=num_cameras,
            led_start=self.led_start,
            led_end=self.led_end,
            detection_timeout=5.0,
            led_stabilization_delay=0.05,
        )

        # Create detector workers
        self.detector_workers = []
        for camera_id, axis_cfg in enumerate(axis_configs):
            # Each camera gets its own view_id (starting from current_view)
            view_id = self.current_view + camera_id

            worker = DetectorWorkerProcess(
                camera_id=camera_id,
                view_id=view_id,
                device=None,  # Not used for AXIS cameras
                dark_exposure=self.exposure,
                threshold=self.threshold,
                command_queue=self.coordinator.get_command_queue(camera_id),
                result_queue=self.coordinator.get_result_queue(),
                display=True,  # Show camera feed for each camera
                axis_config=axis_cfg,
            )

            # Connect worker outputs
            worker.add_output_queue(self.sfm.get_input_queue())
            worker.add_output_queue(self.file_writer.get_2d_input_queue())
            # Note: detector_update_queue is not used in multi-cam mode

            self.detector_workers.append(worker)

        # Start processes
        self.sfm.start()
        self.renderer3d.start()
        self.file_writer.start()
        self.coordinator.start()
        for worker in self.detector_workers:
            worker.start()

        # Get LED count from coordinator
        self.led_count = self.coordinator.get_led_count()
        self.led_id_range = range(
            self.led_start, min(self.led_end + 1, self.led_count)
        )

        # Placeholder attribute for compatibility
        self.detector = None

        logger.info(
            f"Multi-camera mode initialized: {num_cameras} cameras, "
            f"view IDs {self.current_view} to {self.current_view + num_cameras - 1}"
        )

    def check_for_crash(self):
        if self.multi_camera_mode:
            if not self.coordinator.is_alive():
                raise Exception("Coordinator has stopped unexpectedly")
            for i, worker in enumerate(self.detector_workers):
                if not worker.is_alive():
                    raise Exception(f"Detector worker {i} has stopped unexpectedly")
        else:
            if not self.detector.is_alive():
                raise Exception("LED Detector has stopped unexpectedly")

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

    def get_camera_command_queue(self):
        """Return the camera command queue for sending commands to detector."""
        if self.multi_camera_mode:
            # Multi-camera mode doesn't support camera commands (no display)
            logger.warning("Camera command queue not available in multi-camera mode")
            return None
        else:
            return self.detector.get_camera_command_queue()

    def close(self):
        logger.debug("scanner closing")

        if self.multi_camera_mode:
            # Stop coordinator and workers
            self.coordinator.stop()
            # Workers will stop when coordinator sends SCAN_COMPLETE

            # Signal common processes to stop
            self.sfm.stop()
            self.renderer3d.stop()
            self.file_writer.stop()

            # Join processes
            join_with_warning(self.coordinator, "coordinator", timeout=3)
            for i, worker in enumerate(self.detector_workers):
                join_with_warning(worker, f"detector_worker_{i}", timeout=3)
            join_with_warning(self.sfm, "SFM", timeout=3)
            join_with_warning(self.file_writer, "File Writer", timeout=3)
            join_with_warning(self.renderer3d, "Visualiser", timeout=3)
        else:
            # Single camera mode (existing behavior)
            self.detector.stop()
            self.sfm.stop()
            self.renderer3d.stop()
            self.file_writer.stop()

            join_with_warning(self.detector, "detector", timeout=3)
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

        while True:

            start_scan = get_user_confirmation("Start scan? [y/n]: ")

            if not start_scan:
                print("Exiting Marimapper, please wait")
                return

            self.check_for_crash()

            if len(self.led_id_range) == 0:
                print("LED range is zero, are you using a dummy backend?")
                continue

            if self.multi_camera_mode:
                # Multi-camera mode: Signal coordinator to start
                logger.info("Starting multi-camera scan...")
                self.coordinator.start_scan()

                # Wait for completion
                self.coordinator.wait_for_scan_complete()
                logger.info("Multi-camera scan complete!")

                # Increment view counter by number of cameras
                self.current_view += len(self.detector_workers)
            else:
                # Single-camera mode (existing behavior)
                self.detector.detect(
                    self.led_id_range.start, self.led_id_range.stop, self.current_view
                )

                success = self.wait_for_scan()

                if success:
                    self.current_view += 1
