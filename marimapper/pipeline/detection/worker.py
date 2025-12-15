"""
Detection worker process.

This module provides a process-based worker for LED detection that responds to
coordinator commands. Used identically for single-camera or multi-camera setups.

The worker handles:
- Camera initialization and lifecycle
- Command processing (detect, check darkness, set mask, etc.)
- LED detection with adaptive timeouts
- Frame display (GUI or OpenCV window)
- Result reporting back to coordinator

Architecture:
- Runs in separate process (multiprocessing.Process)
- Receives commands via command_queue
- Sends results via result_queue
- Optionally sends frames via frame_queue (for GUI)
- Sends detection data via output_queues (for SFM, FileWriter, etc.)
"""

from multiprocessing import Process, Queue, get_logger
import time
import queue
from typing import Optional, List
import numpy as np
import cv2

from marimapper.camera import Camera
from marimapper.led import LED2D, Point2D
from marimapper.queues import Queue2D, DetectionControlEnum
from marimapper.timeout_controller import TimeoutController

from .algorithms import find_led_in_image, draw_led_detections, draw_error_detection
from .camera_control import set_cam_dark, set_cam_default
from .commands import DetectionCommand, DetectionResult, create_result

logger = get_logger()


class DetectionWorker(Process):
    """
    Single camera detection worker that responds to coordinator commands.

    This worker is used identically for single-camera (N=1) or multi-camera (N>1) setups.
    It handles one camera and processes detection commands from a coordinator.
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
        display: bool = True,
        axis_config: Optional[dict] = None,
        camera_config=None,  # CameraConfig object from core.config
        frame_queue: Optional[Queue] = None,
        detection_timeout: float = 1.5,
    ):
        """
        Initialize detection worker.

        Args:
            camera_id: Unique ID for this camera (0, 1, 2, ...)
            view_id: View ID for SFM reconstruction
            device: Device ID for USB camera (ignored if axis_config or camera_config provided)
            dark_exposure: Exposure setting for dark mode
            threshold: LED detection threshold (0-255)
            command_queue: Queue to receive commands from coordinator
            result_queue: Queue to send results to coordinator
            display: Whether to display camera feed
            axis_config: Configuration for AXIS IP camera (legacy)
            camera_config: CameraConfig object (new method via JSON config file)
            frame_queue: Optional queue for sending frames to GUI
            detection_timeout: Max seconds to wait for detection before skipping
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
        self.camera_config = camera_config
        self.frame_queue = frame_queue

        # Output queues (will be set via add_output_queue)
        self._output_queues: List[Queue2D] = []

        # Timeout controller for adaptive detection timing
        self._timeout_controller = TimeoutController(default_timeout_sec=detection_timeout)

        # Camera state
        self._in_dark_mode = False
        self._window_name = f"MariMapper - Camera {self.camera_id}"
        self._window_initialized = False
        self._preview_error_logged = False

        # Mask state
        self._mask = None  # numpy array (H, W) uint8
        self._mask_resolution = None  # (height, width) of original mask

        # Statistics
        self.detections_attempted = 0
        self.detections_successful = 0

    def add_output_queue(self, queue: Queue2D):
        """
        Add an output queue for sending detection results.

        Output queues receive LED2D objects (for SFM), skip notifications (for FileWriter),
        and scan completion signals.

        Args:
            queue: Queue2D instance to add
        """
        self._output_queues.append(queue)

    def _send_result(self, result_type: str, data=None):
        """
        Send result to coordinator via result queue.

        Args:
            result_type: Result type string (see DetectionResult enum)
            data: Optional result data (e.g., detection position dict)
        """
        try:
            self.result_queue.put((result_type, self.camera_id, data))
        except Exception as e:
            logger.error(f"Camera {self.camera_id}: Failed to send result '{result_type}': {e}")

    def _send_to_output_queues(self, control: DetectionControlEnum, data):
        """
        Send data to all output queues (e.g., SFM, FileWriter, GUI update).

        Args:
            control: Control enum (DETECT, SKIP, DONE)
            data: Data to send (LED2D for DETECT, led_id for SKIP, view_id for DONE)
        """
        for queue in self._output_queues:
            try:
                queue.put(control, data)
            except Exception as e:
                logger.warning(f"Camera {self.camera_id}: Failed to send to output queue: {e}")

    def _show_frame(self, cam: Camera, led_detection: Optional[Point2D] = None):
        """
        Show a live preview frame with optional LED detection overlay.

        Sends to GUI frame queue if available, otherwise uses cv2.imshow.

        Args:
            cam: Camera instance
            led_detection: Optional detected LED position to overlay
        """
        if not self.display:
            return

        try:
            frame = cam.read()
            if frame is None:
                return

            # Draw detection overlay if provided
            if led_detection is not None:
                rendered_frame = draw_led_detections(frame, led_detection)
            else:
                rendered_frame = frame

            # Send to GUI frame queue if provided
            if self.frame_queue is not None:
                try:
                    self.frame_queue.put_nowait(rendered_frame)
                except queue.Full:
                    pass  # Skip frame if queue full
            else:
                # Fallback to cv2.imshow for CLI
                if not self._window_initialized:
                    cv2.namedWindow(self._window_name, cv2.WINDOW_NORMAL)
                    self._window_initialized = True
                cv2.imshow(self._window_name, rendered_frame)
                cv2.waitKey(1)

        except Exception as e:
            if not self._preview_error_logged:
                logger.warning(f"Camera {self.camera_id}: Frame display error: {e}")
                self._preview_error_logged = True

    def _check_darkness(self, cam: Camera) -> bool:
        """
        Check if camera sees any LED (false positive check).

        This verifies that all LEDs are off before starting detection.

        Args:
            cam: Camera instance

        Returns:
            True if no LED visible (check passed), False if LED detected (check failed)
        """
        # Ensure we're in dark mode
        if not self._in_dark_mode:
            set_cam_dark(cam, self.dark_exposure)
            cam.eat()
            self._in_dark_mode = True

        # Check for LED visibility
        image = cam.read()
        led_detection = find_led_in_image(
            image, self.threshold, self._mask, self._mask_resolution
        )

        if led_detection is not None:
            # LED visible when all should be off - this is an error!
            logger.error(
                f"Camera {self.camera_id}: Darkness check FAILED - "
                f"LED visible at position ({led_detection.u():.3f}, {led_detection.v():.3f}) "
                f"when all should be off"
            )

            # Show the false positive LED with RED marker to help user identify the issue
            if self.display:
                rendered_frame = draw_error_detection(image, led_detection)

                # Send to GUI or display
                if self.frame_queue is not None:
                    try:
                        # Clear queue and send error frame
                        while not self.frame_queue.empty():
                            try:
                                self.frame_queue.get_nowait()
                            except:
                                break
                        self.frame_queue.put_nowait(rendered_frame)
                    except:
                        pass
                else:
                    # CLI mode - show window
                    if not self._window_initialized:
                        cv2.namedWindow(self._window_name, cv2.WINDOW_NORMAL)
                        self._window_initialized = True
                    cv2.imshow(self._window_name, rendered_frame)
                    cv2.waitKey(1)

                # Keep the error frame visible for a moment
                time.sleep(2.0)  # 2 seconds to see the red marker

                # Continue showing the error frame
                for _ in range(10):  # Show for ~1 more second
                    if self.frame_queue is not None:
                        try:
                            self.frame_queue.put_nowait(rendered_frame)
                        except:
                            pass
                    time.sleep(0.1)

            return False

        # No LED detected - darkness check passed
        logger.debug(f"Camera {self.camera_id}: Darkness check PASSED")
        # Show normal frame
        self._show_frame(cam, led_detection)
        return True

    def _detect_led(self, cam: Camera, led_id: int) -> tuple[bool, Optional[Point2D]]:
        """
        Detect a single LED.

        The LED is already ON (controlled by coordinator). This method polls the camera
        until the LED is detected or timeout occurs.

        Uses adaptive timeout based on previous response times.

        Args:
            cam: Camera instance
            led_id: LED ID to detect

        Returns:
            Tuple of (success: bool, position: Optional[Point2D])
        """
        self.detections_attempted += 1

        # Ensure we're in dark mode
        if not self._in_dark_mode:
            set_cam_dark(cam, self.dark_exposure)
            cam.eat()  # Flush buffered frames
            self._in_dark_mode = True

        # Wait for LED to stabilize (coordinator just turned it on)
        time.sleep(0.03)

        # Poll for detection with adaptive timeout
        start_time = time.time()
        deadline = start_time + max(0.1, self._timeout_controller.timeout)

        led_detection = None

        while time.time() < deadline:
            # Read frame and attempt detection
            image = cam.read()
            led_detection = find_led_in_image(
                image, self.threshold, self._mask, self._mask_resolution
            )

            # Show frame with detection overlay
            self._show_frame(cam, led_detection)

            if led_detection is not None:
                # Success!
                response_time = time.time() - start_time
                self._timeout_controller.add_response_time(response_time)
                self.detections_successful += 1

                # Create LED2D and send to output queues
                led_2d = LED2D(led_id, self.view_id, led_detection)
                self._send_to_output_queues(DetectionControlEnum.DETECT, led_2d)

                logger.debug(
                    f"Camera {self.camera_id}: Detected LED {led_id} at "
                    f"({led_detection.u():.3f}, {led_detection.v():.3f}) "
                    f"in {response_time:.3f}s"
                )

                return (True, led_detection)

            # Brief pause before next attempt
            time.sleep(0.02)

        # Timeout - no detection
        self._send_to_output_queues(DetectionControlEnum.SKIP, led_id)
        logger.debug(
            f"Camera {self.camera_id}: Failed to detect LED {led_id} "
            f"within {self._timeout_controller.timeout:.2f}s timeout"
        )

        return (False, None)

    def _handle_command(self, cam: Camera, command_msg) -> bool:
        """
        Handle a single command from the coordinator.

        Args:
            cam: Camera instance
            command_msg: Tuple of (command_type, *args)

        Returns:
            True to continue processing, False to exit worker
        """
        if not isinstance(command_msg, tuple) or len(command_msg) < 1:
            logger.warning(f"Camera {self.camera_id}: Invalid command format: {command_msg}")
            return True

        command_type = command_msg[0]

        # CHECK_DARKNESS: Verify no LED visible
        if command_type == DetectionCommand.CHECK_DARKNESS.value:
            is_clear = self._check_darkness(cam)
            result_type = DetectionResult.DARKNESS_CLEAR.value if is_clear else DetectionResult.DARKNESS_FAIL.value
            self._send_result(result_type)

        # DETECT_LED: Detect specified LED
        elif command_type == DetectionCommand.DETECT_LED.value:
            if len(command_msg) < 2:
                logger.error(f"Camera {self.camera_id}: DETECT_LED missing led_id")
                return True

            led_id = command_msg[1]
            success, position = self._detect_led(cam, led_id)

            if success:
                self._send_result(
                    DetectionResult.DETECT_SUCCESS.value,
                    {
                        "led_id": led_id,
                        "x": position.u(),
                        "y": position.v(),
                    },
                )
            else:
                self._send_result(DetectionResult.DETECT_FAIL.value, {"led_id": led_id})

        # REDETECT_LED: Re-detect for movement check
        elif command_type == DetectionCommand.REDETECT_LED.value:
            if len(command_msg) < 2:
                logger.error(f"Camera {self.camera_id}: REDETECT_LED missing led_id")
                return True

            led_id = command_msg[1]
            success, position = self._detect_led(cam, led_id)

            if success:
                self._send_result(
                    DetectionResult.REDETECT_SUCCESS.value,
                    {
                        "led_id": led_id,
                        "x": position.u(),
                        "y": position.v(),
                    },
                )
            else:
                self._send_result(DetectionResult.REDETECT_FAIL.value, {"led_id": led_id})

        # SCAN_COMPLETE: Reset to preview mode
        elif command_type == DetectionCommand.SCAN_COMPLETE.value:
            logger.info(f"Camera {self.camera_id}: Received SCAN_COMPLETE")
            try:
                set_cam_default(cam)
                cam.eat()
                self._in_dark_mode = False
                logger.info(f"Camera {self.camera_id}: Reset to preview mode")
            except Exception as e:
                logger.warning(
                    f"Camera {self.camera_id}: Failed to reset exposure: {e}"
                )

            # Send DONE to output queues
            self._send_to_output_queues(DetectionControlEnum.DONE, self.view_id)

        # SET_MASK: Update detection mask
        elif command_type == DetectionCommand.SET_MASK.value:
            if len(command_msg) < 2:
                logger.error(f"Camera {self.camera_id}: SET_MASK missing data")
                return True

            mask_dict = command_msg[1]
            if isinstance(mask_dict, dict):
                mask_data = mask_dict.get("mask")
                mask_res = mask_dict.get("resolution")

                if mask_data is None:
                    # Clear mask
                    self._mask = None
                    self._mask_resolution = None
                    logger.info(f"Camera {self.camera_id}: Mask cleared")
                else:
                    self._mask = mask_data
                    self._mask_resolution = mask_res
                    masked_pixels = np.sum(mask_data == 0)
                    logger.info(
                        f"Camera {self.camera_id}: Mask set - "
                        f"resolution {mask_res}, masked pixels: {masked_pixels}"
                    )

        # SET_DARK: Switch to dark exposure mode
        elif command_type == DetectionCommand.SET_DARK.value:
            try:
                set_cam_dark(cam, self.dark_exposure)
                cam.eat()
                self._in_dark_mode = True
                logger.info(f"Camera {self.camera_id}: Set to DARK mode")
            except Exception as e:
                logger.warning(f"Camera {self.camera_id}: Failed to set dark mode: {e}")

        # SET_BRIGHT: Switch to bright/preview mode
        elif command_type == DetectionCommand.SET_BRIGHT.value:
            try:
                set_cam_default(cam)
                cam.eat()
                self._in_dark_mode = False
                logger.info(f"Camera {self.camera_id}: Set to BRIGHT mode")
            except Exception as e:
                logger.warning(f"Camera {self.camera_id}: Failed to set bright mode: {e}")

        # SET_THRESHOLD: Update detection threshold
        elif command_type == DetectionCommand.SET_THRESHOLD.value:
            if len(command_msg) < 2:
                logger.error(f"Camera {self.camera_id}: SET_THRESHOLD missing value")
                return True

            new_threshold = command_msg[1]
            self.threshold = new_threshold
            logger.info(f"Camera {self.camera_id}: Threshold set to {new_threshold}")

        # APPLY_CONFIG: Apply settings from config file (AXIS cameras only)
        elif command_type == DetectionCommand.APPLY_CONFIG.value:
            try:
                # Only apply if this is a VAPIX camera
                from marimapper.camera.settings_controller import VAPIXSettingsController
                if isinstance(cam._settings_controller, VAPIXSettingsController):
                    # Apply config from default location
                    success = cam._settings_controller.apply_config()
                    if success:
                        logger.info(f"Camera {self.camera_id}: Applied config file successfully")
                    else:
                        logger.warning(f"Camera {self.camera_id}: Some config settings failed to apply")
                    cam.eat()  # Flush buffered frames after settings change
                else:
                    logger.debug(f"Camera {self.camera_id}: Not an AXIS camera, ignoring APPLY_CONFIG")
            except Exception as e:
                logger.error(f"Camera {self.camera_id}: Failed to apply config: {e}")

        # EXIT: Shutdown
        elif command_type == DetectionCommand.EXIT.value:
            logger.info(f"Camera {self.camera_id}: Received EXIT command")
            return False  # Signal to exit main loop

        else:
            logger.warning(f"Camera {self.camera_id}: Unknown command: {command_type}")

        return True  # Continue processing

    def run(self):
        """
        Main detector loop - listen for commands and execute.

        This is the entry point when the process starts.
        """
        try:
            logger.info(
                f"DetectionWorker {self.camera_id} starting "
                f"(view_id={self.view_id}, axis={self.axis_config is not None})..."
            )

            # Initialize camera
            if self.camera_config is not None:
                # New method: use CameraConfig object
                cam = Camera.from_config(self.camera_config)
            else:
                # Legacy method: use device/axis_config
                cam = Camera.from_legacy_config(device_name=self.device, axis_config=self.axis_config)
            logger.info(f"Camera {self.camera_id}: Connected successfully")

            # Start in bright/preview mode
            set_cam_default(cam)
            self._in_dark_mode = False
            logger.info(f"Camera {self.camera_id}: Set to preview mode")

            # Prepare window for display if enabled
            if self.display and self.frame_queue is None:
                cv2.namedWindow(self._window_name, cv2.WINDOW_NORMAL)
                self._window_initialized = True

        except Exception as e:
            logger.error(f"Camera {self.camera_id}: Failed to initialize: {e}")
            import traceback
            traceback.print_exc()
            self._send_result(DetectionResult.ERROR.value, f"Initialization failed: {e}")
            return

        # Main command loop
        logger.info(f"Camera {self.camera_id}: Ready and waiting for commands")

        try:
            while True:
                # Wait for command from coordinator
                try:
                    command_msg = self.command_queue.get(timeout=0.03)
                except queue.Empty:
                    # No command yet; show live preview if display enabled
                    # Keep preview running even in dark mode so the GUI feed doesn't freeze
                    if self.display:
                        self._show_frame(cam)
                    continue

                # Handle command
                should_continue = self._handle_command(cam, command_msg)
                if not should_continue:
                    break  # EXIT command received

        except KeyboardInterrupt:
            logger.info(f"Camera {self.camera_id}: Interrupted by user")

        except Exception as e:
            logger.error(f"Camera {self.camera_id}: Error in command loop: {e}")
            import traceback
            traceback.print_exc()
            self._send_result(DetectionResult.ERROR.value, f"Command loop error: {e}")

        finally:
            # Cleanup
            logger.info(f"Camera {self.camera_id}: Cleaning up...")

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
                logger.warning(f"Camera {self.camera_id}: Failed to release camera: {e}")

            # Close OpenCV window if display was enabled
            if self.display and self._window_initialized:
                try:
                    cv2.destroyWindow(self._window_name)
                    logger.info(f"Camera {self.camera_id}: Window closed")
                except Exception as e:
                    logger.warning(f"Camera {self.camera_id}: Failed to close window: {e}")
