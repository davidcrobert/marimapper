"""
DetectorWorkerProcess - Individual camera worker for multi-camera scanning.

This process handles a single camera in a multi-camera setup:
1. Captures images from assigned camera
2. Detects LED positions when commanded by CoordinatorProcess
3. Reports results back to coordinator
4. Sends successful detections to Queue2D for SFM reconstruction

Unlike DetectorProcess, this worker does NOT control the LED backend -
that's handled by the CoordinatorProcess for synchronization.
"""

from multiprocessing import Process, Queue, get_logger
import time
import queue
from typing import List, Optional
import numpy as np

from marimapper.camera import Camera
from marimapper.detector import set_cam_dark, set_cam_default, find_led_in_image, draw_led_detections
from marimapper.led import LED2D, Point2D
from marimapper.queues import Queue2D, DetectionControlEnum
from marimapper.timeout_controller import TimeoutController
import cv2

logger = get_logger()


class DetectorWorkerProcess(Process):
    """
    Worker process that handles a single camera in multi-camera mode.
    Listens for commands from CoordinatorProcess and reports results.
    """

    def __init__(
        self,
        camera_id: int,
        view_id: int,
        device: Optional[str],
        dark_exposure: int,
        threshold: int,
        command_queue: Queue,
        result_queue: Queue,
        display: bool = False,
        axis_config: Optional[dict] = None,
        detection_timeout: float = 1.5,
        frame_queue: Optional[Queue] = None,
    ):
        """
        Initialize detector worker.

        Args:
            camera_id: Unique ID for this camera (0, 1, 2, ...)
            view_id: View ID for SFM reconstruction (same as camera_id typically)
            device: Device ID for USB camera (ignored if axis_config provided)
            dark_exposure: Exposure setting for dark mode
            threshold: LED detection threshold
            command_queue: Queue to receive commands from coordinator
            result_queue: Queue to send results to coordinator
            display: Whether to display camera feed (usually False for multi-cam)
            axis_config: Configuration for AXIS IP camera
            detection_timeout: Max seconds to wait for a detection before skipping
            frame_queue: Optional queue for sending frames to GUI (instead of cv2.imshow)
        """
        super().__init__()
        self.camera_id = camera_id
        self.view_id = view_id
        self.device = device
        self.dark_exposure = dark_exposure
        self.threshold = threshold
        self.command_queue = command_queue
        self.result_queue = result_queue
        self.display = display
        self.axis_config = axis_config
        self.detection_timeout = detection_timeout
        self._frame_queue = frame_queue
        self._window_name = f"MariMapper - Camera {self.camera_id}"
        self._preview_error_logged = False
        self._window_initialized = False
        self._timeout_controller = TimeoutController(
            default_timeout_sec=detection_timeout
        )
        self._in_scan = False

        # Output queues (will be set via add_output_queue)
        self._output_queues: List[Queue2D] = []

        # Statistics
        self.detections_attempted = 0
        self.detections_successful = 0

        # Mask state
        self._mask = None  # numpy array (H, W) uint8
        self._mask_resolution = None  # (height, width) of original mask

    def add_output_queue(self, queue: Queue2D):
        """Add an output queue for sending detection results (e.g., to SFM)."""
        self._output_queues.append(queue)

    def _find_led_with_display(self, cam: Camera) -> Optional[Point2D]:
        """
        Find LED with unique window name for this camera.
        Similar to find_led() but with camera-specific window.
        """
        image = cam.read()
        results = find_led_in_image(
            image, self.threshold, self._mask, self._mask_resolution
        )

        if self.display:
            rendered_image = draw_led_detections(image, results)

            # Send to GUI frame queue if provided
            if self._frame_queue is not None:
                try:
                    self._frame_queue.put_nowait(rendered_image)
                except queue.Full:
                    pass  # Skip frame if queue full
            else:
                # Fallback to cv2.imshow for CLI
                window_name = f"MariMapper - Camera {self.camera_id}"
                cv2.imshow(window_name, rendered_image)
                cv2.waitKey(1)

        return results

    def _send_result(
        self,
        led_id: int,
        success: bool,
        x: Optional[float] = None,
        y: Optional[float] = None,
    ):
        """Send detection result to coordinator."""
        try:
            self.result_queue.put(("RESULT", self.camera_id, led_id, success, x, y))
        except Exception as e:
            logger.error(
                f"Camera {self.camera_id}: Failed to send result for LED {led_id}: {e}"
            )

    def _send_error(self, error_msg: str):
        """Send error message to coordinator."""
        try:
            self.result_queue.put(("ERROR", self.camera_id, error_msg))
        except Exception as e:
            logger.error(
                f"Camera {self.camera_id}: Failed to send error message: {e}"
            )

    def _send_to_output_queues(self, control: DetectionControlEnum, data):
        """Send data to all output queues (e.g., SFM, FileWriter)."""
        for queue in self._output_queues:
            try:
                queue.put(control, data)
            except Exception as e:
                logger.warning(
                    f"Camera {self.camera_id}: Failed to send to output queue: {e}"
                )

    def _show_live_preview(self, cam: Camera):
        """
        Show a live preview frame when idle so the window is visible before scans.
        This only runs when display=True.
        """
        try:
            frame = cam.read()
            if frame is None:
                return

            if self._frame_queue is not None:
                # Send to GUI frame queue
                try:
                    self._frame_queue.put_nowait(frame)
                except queue.Full:
                    pass  # Skip frame if queue full
            else:
                # Fallback to cv2.imshow for CLI
                if not self._window_initialized:
                    cv2.namedWindow(self._window_name, cv2.WINDOW_NORMAL)
                    self._window_initialized = True
                cv2.imshow(self._window_name, frame)
                cv2.waitKey(1)
        except Exception as e:
            if not self._preview_error_logged:
                logger.warning(f"Camera {self.camera_id}: Live preview error: {e}")
                self._preview_error_logged = True

    def _detect_and_report(self, cam: Camera, led_id: int):
        """
        Detect LED and report result to coordinator.

        The LED should already be turned on by the coordinator before this is called.
        """
        self.detections_attempted += 1
        if not self._in_scan:
            try:
                set_cam_dark(cam, self.dark_exposure)
                cam.eat()  # flush buffered frames so we see fresh LED state
                self._in_scan = True
                logger.info(f"Camera {self.camera_id}: Entered scan mode (dark exposure)")
            except Exception as e:
                logger.warning(f"Camera {self.camera_id}: Failed to set dark exposure at scan start: {e}")

        # Allow the LED to stabilize after being turned on by coordinator
        time.sleep(0.03)

        # Adaptive timeout based on previous response times (like single-cam TimeoutController)
        deadline = time.time() + max(0.1, self._timeout_controller.timeout)
        start_time = time.time()

        try:
            while True:
                # Attempt detection
                led_detection = self._find_led_with_display(cam)

                if led_detection is not None:
                    # Success!
                    self.detections_successful += 1
                    self._timeout_controller.add_response_time(time.time() - start_time)

                    # Send result to coordinator
                    self._send_result(led_id, True, led_detection.u(), led_detection.v())

                    # Send to SFM and other output queues
                    led_2d = LED2D(led_id, self.view_id, led_detection)
                    self._send_to_output_queues(DetectionControlEnum.DETECT, led_2d)

                    logger.debug(
                        f"Camera {self.camera_id}: Detected LED {led_id} at "
                        f"({led_detection.u():.3f}, {led_detection.v():.3f})"
                    )
                    return

                # No detection yet; check timeout
                if time.time() >= deadline:
                    break

                # Small delay to allow next frame
                time.sleep(0.02)

        except Exception as e:
            logger.error(
                f"Camera {self.camera_id}: Exception during LED {led_id} detection: {e}"
            )

        # Failed to detect within timeout
        self._send_result(led_id, False, None, None)
        self._send_to_output_queues(DetectionControlEnum.SKIP, led_id)
        logger.debug(f"Camera {self.camera_id}: Failed to detect LED {led_id} within timeout")

    def run(self):
        """Main worker loop - listen for commands and detect LEDs."""
        try:
            logger.info(
                f"DetectorWorkerProcess {self.camera_id} starting "
                f"(view_id={self.view_id}, axis={self.axis_config is not None})..."
            )

            # Initialize camera
            cam = Camera(device_id=self.device, axis_config=self.axis_config)
            logger.info(f"Camera {self.camera_id}: Connected successfully")

            # Default to bright/normal when idle so user can see preview
            set_cam_default(cam)
            logger.info(f"Camera {self.camera_id}: Set to bright/preview mode")

            # Prepare resizable window for previews/detections
            if self.display:
                cv2.namedWindow(self._window_name, cv2.WINDOW_NORMAL)
                self._window_initialized = True

        except Exception as e:
            logger.error(
                f"Camera {self.camera_id}: Failed to initialize: {e}"
            )
            import traceback
            traceback.print_exc()
            self._send_error(f"Initialization failed: {e}")
            return

        # Main command loop
        logger.info(f"Camera {self.camera_id}: Ready and waiting for commands")

        try:
            while True:
                # Wait for command from coordinator
                try:
                    msg = self.command_queue.get(timeout=0.03)
                except queue.Empty:
                    # No command yet; if display enabled, keep window alive with live feed
                    if self.display:
                        self._show_live_preview(cam)
                    continue

                msg_type = msg[0]

                if msg_type == "DETECT_LED":
                    led_id = msg[1]
                    self._detect_and_report(cam, led_id)

                elif msg_type == "SCAN_COMPLETE":
                    logger.info(f"Camera {self.camera_id}: Received SCAN_COMPLETE")
                    # Return to bright/preview mode after scan and keep preview open
                    try:
                        set_cam_default(cam)
                        cam.eat()
                        logger.info(f"Camera {self.camera_id}: Exited scan mode (bright)")
                    except Exception as e:
                        logger.warning(f"Camera {self.camera_id}: Failed to reset exposure after scan: {e}")
                    self._in_scan = False
                    # keep looping for idle preview

                elif msg_type == "SET_MASK":
                    # Handle mask update command
                    mask_dict = msg[1] if len(msg) > 1 else None
                    if mask_dict is not None and isinstance(mask_dict, dict):
                        mask_data = mask_dict.get("mask")
                        mask_res = mask_dict.get("resolution")

                        if mask_data is None:
                            # Clear mask
                            self._mask = None
                            self._mask_resolution = None
                            logger.info(f"Camera {self.camera_id}: Detection mask cleared")
                        else:
                            self._mask = mask_data
                            self._mask_resolution = mask_res
                            masked_pixels = np.sum(mask_data == 0)
                            logger.info(
                                f"Camera {self.camera_id}: Detection mask set: "
                                f"resolution {mask_res}, masked pixels: {masked_pixels}"
                            )

                elif msg_type == "EXIT":
                    logger.info(f"Camera {self.camera_id}: Received EXIT")
                    break

                else:
                    logger.warning(
                        f"Camera {self.camera_id}: Unknown command: {msg_type}"
                    )

        except KeyboardInterrupt:
            logger.info(f"Camera {self.camera_id}: Interrupted by user")

        except Exception as e:
            logger.error(
                f"Camera {self.camera_id}: Error in command loop: {e}"
            )
            import traceback
            traceback.print_exc()
            self._send_error(f"Command loop error: {e}")

        finally:
            # Cleanup
            logger.info(f"Camera {self.camera_id}: Cleaning up...")

            # Send completion signal to output queues
            self._send_to_output_queues(DetectionControlEnum.DONE, self.view_id)

            # Report statistics
            if self.detections_attempted > 0:
                success_rate = (
                    self.detections_successful / self.detections_attempted * 100
                )
                logger.info(
                    f"Camera {self.camera_id}: Detected {self.detections_successful}/"
                    f"{self.detections_attempted} LEDs ({success_rate:.1f}% success)"
                )

            # Reset camera and release
            try:
                set_cam_default(cam)
                cam.device.release()
                logger.info(f"Camera {self.camera_id}: Camera released")
            except Exception as e:
                logger.warning(
                    f"Camera {self.camera_id}: Failed to release camera: {e}"
                )

            # Close OpenCV window if display was enabled
            if self.display:
                try:
                    window_name = f"MariMapper - Camera {self.camera_id}"
                    cv2.destroyWindow(window_name)
                    logger.info(f"Camera {self.camera_id}: Window closed")
                except Exception as e:
                    logger.warning(f"Camera {self.camera_id}: Failed to close window: {e}")
