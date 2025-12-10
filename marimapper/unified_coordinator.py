"""
UnifiedCoordinator - Coordinates LED scanning across one or more camera detectors.

This process controls the LED backend and synchronizes detection across multiple
UnifiedDetector instances. Works identically whether N=1 or N=9 detectors.

Key responsibilities:
- Control LED backend (turn LEDs on/off)
- Coordinate darkness check (false positive prevention)
- Synchronize LED-by-LED detection across all detectors
- Perform movement check at scan end
- Signal scan completion/failure to output queues
"""

from multiprocessing import Process, Queue, Event, get_logger
import time
from functools import partial
from typing import Dict, List, Optional
from marimapper.queues import Queue2D, DetectionControlEnum
from marimapper.led import get_distance, Point2D

logger = get_logger()


class UnifiedCoordinator(Process):
    """
    Coordinates LED scanning across one or more camera detectors.
    Handles LED backend control and synchronization.
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
        """
        Initialize the coordinator process.

        Args:
            backend_factory: Factory function to create LED backend instance
            num_detectors: Number of detector processes to coordinate
            led_start: First LED index to scan
            led_end: Last LED index to scan (exclusive)
            check_movement: Whether to perform movement check at end of scan
            detection_timeout: Max time to wait for all detectors (seconds)
            led_stabilization_delay: Time to wait after turning LED on (seconds)
        """
        super().__init__()
        self.backend_factory = backend_factory
        self.num_detectors = num_detectors
        self.led_start = led_start
        self.led_end = led_end
        self.check_movement = check_movement
        self.detection_timeout = detection_timeout
        self.led_stabilization_delay = led_stabilization_delay

        # Communication queues
        self._detector_command_queues: List[Queue] = []
        self._detector_result_queue = Queue()  # Shared queue for all detector results
        self._led_count_queue = Queue()  # For returning LED count to Scanner
        self._scan_request_queue = Queue()  # For receiving scan requests
        self._cancel_event = Event()  # Signal to cancel current scan
        self._exit_event = Event()  # Signal to exit process

        # Output queues for sending scan status to GUI/SFM/FileWriter
        self._output_queues: List[Queue2D] = []

        # Initialize command queues for each detector
        for detector_id in range(num_detectors):
            cmd_queue = Queue()
            cmd_queue.cancel_join_thread()
            self._detector_command_queues.append(cmd_queue)

        self._detector_result_queue.cancel_join_thread()
        self._led_count_queue.cancel_join_thread()
        self._scan_request_queue.cancel_join_thread()

        # Statistics tracking
        self.detector_success_counts: Dict[int, int] = {i: 0 for i in range(num_detectors)}
        self.detector_failure_counts: Dict[int, int] = {i: 0 for i in range(num_detectors)}

    def get_command_queue(self, detector_id: int) -> Queue:
        """Get the command queue for a specific detector."""
        return self._detector_command_queues[detector_id]

    def get_result_queue(self) -> Queue:
        """Get the result queue (shared by all detectors)."""
        return self._detector_result_queue

    def get_led_count(self) -> int:
        """Get LED count from backend (blocks until available)."""
        return self._led_count_queue.get()

    def add_output_queue(self, queue: Queue2D):
        """Add an output queue for sending scan status updates."""
        self._output_queues.append(queue)

    def request_scan(self, led_from: int, led_to: int, view_id: int):
        """Request a scan to be performed (called from Scanner/GUI)."""
        self._scan_request_queue.put((led_from, led_to, view_id))

    def cancel_scan(self):
        """Cancel the current scan."""
        self._cancel_event.set()

    def stop(self):
        """Signal coordinator to exit."""
        self._exit_event.set()
        # Tell all detectors to exit cleanly
        for detector_id, cmd_queue in enumerate(self._detector_command_queues):
            try:
                cmd_queue.put(("EXIT",), timeout=0.5)
            except Exception as e:
                logger.warning(f"Failed to send EXIT to detector {detector_id}: {e}")

    def _send_to_output_queues(self, control: DetectionControlEnum, data):
        """Send status update to all output queues (GUI, SFM, FileWriter)."""
        for queue in self._output_queues:
            try:
                queue.put(control, data)
            except Exception as e:
                logger.warning(f"Failed to send to output queue: {e}")

    def _blacken_backend(self, backend) -> bool:
        """Turn off all LEDs."""
        try:
            # Preferred: dedicated blackout implementation
            if hasattr(backend, "blackout"):
                backend.blackout()
                return True

            # Fallback: bulk-set if supported
            if hasattr(backend, "set_leds"):
                buffer = [[0, 0, 0] for _ in range(backend.get_led_count())]
                backend.set_leds(buffer)
                return True

            # Last resort: iterate per LED
            if hasattr(backend, "set_led"):
                for i in range(backend.get_led_count()):
                    backend.set_led(i, False)
                return True

        except Exception as e:
            logger.warning(f"Failed to blacken backend: {e}")
            return False

    def _wait_for_all_detector_responses(
        self, timeout: float, expected_response_types: List[str]
    ) -> Dict[int, tuple]:
        """
        Wait for all detectors to respond.

        Args:
            timeout: Maximum time to wait (seconds)
            expected_response_types: List of acceptable response types

        Returns:
            Dict mapping detector_id -> (response_type, data)
        """
        responses = {}
        deadline = time.time() + timeout

        while len(responses) < self.num_detectors:
            remaining_time = deadline - time.time()
            if remaining_time <= 0:
                # Timeout - log which detectors didn't respond
                missing = set(range(self.num_detectors)) - set(responses.keys())
                logger.warning(
                    f"Timeout waiting for detectors {missing}. "
                    f"Received {len(responses)}/{self.num_detectors} responses."
                )
                break

            try:
                msg = self._detector_result_queue.get(
                    timeout=min(0.1, max(0.001, remaining_time))
                )

                if len(msg) < 2:
                    logger.warning(f"Invalid response format: {msg}")
                    continue

                response_type = msg[0]
                detector_id = msg[1]
                data = msg[2] if len(msg) > 2 else None

                # Only accept expected response types
                if response_type in expected_response_types or response_type == "ERROR":
                    responses[detector_id] = (response_type, data)

                    # Track statistics for detection results
                    if response_type in ["DETECT_SUCCESS", "REDETECT_SUCCESS"]:
                        self.detector_success_counts[detector_id] += 1
                    elif response_type in ["DETECT_FAIL", "REDETECT_FAIL"]:
                        self.detector_failure_counts[detector_id] += 1

                    if response_type == "ERROR":
                        logger.error(f"Detector {detector_id} error: {data}")

            except Exception:
                # Queue timeout, continue waiting
                continue

        return responses

    def _check_darkness(self, backend) -> bool:
        """
        Perform darkness check - verify no LED is visible.
        Returns True if all clear, False if any detector sees LED.
        """
        logger.info("Performing darkness check (false positive prevention)...")

        # Ensure all LEDs are off
        self._blacken_backend(backend)
        time.sleep(0.1)  # Allow LEDs to fully turn off

        # Broadcast CHECK_DARKNESS to all detectors
        for cmd_queue in self._detector_command_queues:
            cmd_queue.put(("CHECK_DARKNESS",))

        # Wait for all responses
        responses = self._wait_for_all_detector_responses(
            timeout=2.0, expected_response_types=["DARKNESS_CLEAR", "DARKNESS_FAIL"]
        )

        # Check if all detectors reported clear
        all_clear = True
        for detector_id in range(self.num_detectors):
            if detector_id not in responses:
                logger.warning(f"Detector {detector_id} did not respond to darkness check")
                all_clear = False
                continue

            response_type, _ = responses[detector_id]
            if response_type == "DARKNESS_FAIL":
                logger.error(
                    f"Detector {detector_id} can see an LED when all should be off"
                )
                all_clear = False

        if all_clear:
            logger.info("Darkness check PASSED - all detectors clear")
        else:
            logger.error("Darkness check FAILED - aborting scan")

        return all_clear

    def _detect_led_synchronized(self, backend, led_id: int) -> Dict[int, tuple]:
        """
        Coordinate detection of a single LED across all detectors.

        Args:
            backend: LED backend instance
            led_id: LED ID to detect

        Returns:
            Dict mapping detector_id -> (response_type, data)
        """
        # Turn on LED
        backend.set_led(led_id, True)

        # Wait for LED to stabilize
        if self.led_stabilization_delay > 0:
            time.sleep(self.led_stabilization_delay)

        # Broadcast DETECT_LED command to all detectors
        for cmd_queue in self._detector_command_queues:
            try:
                cmd_queue.put(("DETECT_LED", led_id), timeout=1.0)
            except Exception as e:
                logger.error(f"Failed to send DETECT_LED command: {e}")

        # Wait for all results
        results = self._wait_for_all_detector_responses(
            timeout=self.detection_timeout,
            expected_response_types=["DETECT_SUCCESS", "DETECT_FAIL"],
        )

        # Turn off LED
        backend.set_led(led_id, False)

        # Log results
        successful = sum(
            1 for response_type, _ in results.values() if response_type == "DETECT_SUCCESS"
        )
        logger.debug(f"LED {led_id}: {successful}/{self.num_detectors} detectors succeeded")

        return results

    def _check_movement(self, backend, first_led_id: int, original_positions: Dict[int, Point2D]) -> bool:
        """
        Re-detect first LED and compare positions to check for camera movement.

        Args:
            backend: LED backend instance
            first_led_id: LED ID to re-detect (first LED from scan)
            original_positions: Dict mapping detector_id -> Point2D from original detection

        Returns:
            True if movement detected, False if stable
        """
        if not original_positions:
            logger.warning("No original positions for movement check, skipping")
            return False

        logger.info(f"Performing movement check by re-detecting LED {first_led_id}...")

        # Turn LED on
        backend.set_led(first_led_id, True)
        time.sleep(self.led_stabilization_delay)

        # Broadcast REDETECT_LED command
        for cmd_queue in self._detector_command_queues:
            try:
                cmd_queue.put(("REDETECT_LED", first_led_id), timeout=1.0)
            except Exception as e:
                logger.error(f"Failed to send REDETECT_LED command: {e}")

        # Wait for responses
        new_results = self._wait_for_all_detector_responses(
            timeout=self.detection_timeout,
            expected_response_types=["REDETECT_SUCCESS", "REDETECT_FAIL"],
        )

        # Turn LED off
        backend.set_led(first_led_id, False)

        # Compare positions
        movement_detected = False
        for detector_id, original_pos in original_positions.items():
            if detector_id not in new_results:
                logger.warning(f"Detector {detector_id}: No response for movement check")
                continue

            response_type, data = new_results[detector_id]

            if response_type != "REDETECT_SUCCESS":
                logger.warning(
                    f"Detector {detector_id}: Could not re-detect LED {first_led_id} "
                    f"for movement check"
                )
                continue

            # Create Point2D from new position
            new_pos = Point2D(data["x"], data["y"], contours=[])

            # Calculate distance
            distance = get_distance(
                type('LED2D', (), {'point': original_pos})(),
                type('LED2D', (), {'point': new_pos})()
            )

            if distance > 0.01:  # 1% movement threshold
                logger.error(
                    f"Detector {detector_id}: Camera movement of {int(distance * 100)}% detected"
                )
                movement_detected = True

        if movement_detected:
            logger.error("Movement check FAILED - camera(s) moved during scan")
        else:
            logger.info("Movement check PASSED - camera(s) stable")

        return movement_detected

    def _run_scan(self, backend, led_from: int, led_to: int, view_id: int) -> bool:
        """
        Execute a complete scan with all checks.

        Args:
            backend: LED backend instance
            led_from: First LED to scan
            led_to: Last LED to scan (exclusive)
            view_id: View ID for this scan

        Returns:
            True if scan succeeded, False if failed/cancelled
        """
        logger.info(f"Starting scan: LEDs {led_from} to {led_to - 1}, view {view_id}")

        # Clear cancellation flag
        self._cancel_event.clear()

        # Step 1: Darkness Check (false positive prevention)
        if not self._check_darkness(backend):
            self._send_to_output_queues(DetectionControlEnum.FAIL, None)
            return False

        # Step 2: LED-by-LED Detection Loop
        first_led_positions = {}  # For movement check

        for led_id in range(led_from, led_to):
            # Check for cancellation
            if self._cancel_event.is_set():
                logger.info(f"Scan cancelled at LED {led_id}")
                self._send_to_output_queues(DetectionControlEnum.FAIL, None)
                self._blacken_backend(backend)
                return False

            # Detect LED (synchronized across all detectors)
            results = self._detect_led_synchronized(backend, led_id)

            # Report per-LED progress to output queues
            successful = sum(
                1 for response_type, _ in results.values() if response_type == "DETECT_SUCCESS"
            )
            progress_payload = {"led_id": led_id, "view_id": view_id}
            if successful > 0:
                self._send_to_output_queues(DetectionControlEnum.DETECT, progress_payload)
            else:
                self._send_to_output_queues(DetectionControlEnum.SKIP, progress_payload)

            # Store first LED positions for movement check
            if led_id == led_from:
                for detector_id, (response_type, data) in results.items():
                    if response_type == "DETECT_SUCCESS":
                        first_led_positions[detector_id] = Point2D(
                            data["x"], data["y"], contours=[]
                        )

        # Step 3: Movement Check (if enabled and we have reference positions)
        if self.check_movement and first_led_positions:
            movement_detected = self._check_movement(backend, led_from, first_led_positions)

            if movement_detected:
                # Send DELETE signal (view should be deleted due to movement)
                self._send_to_output_queues(DetectionControlEnum.DELETE, view_id)
                self._blacken_backend(backend)
                return False

        # Step 4: Success - Signal Completion
        logger.info(f"Scan completed successfully for view {view_id}")

        # Broadcast SCAN_COMPLETE to all detectors
        for cmd_queue in self._detector_command_queues:
            try:
                cmd_queue.put(("SCAN_COMPLETE",), timeout=1.0)
            except Exception as e:
                logger.error(f"Failed to send SCAN_COMPLETE: {e}")

        # Send DONE to output queues
        self._send_to_output_queues(DetectionControlEnum.DONE, view_id)

        # Blacken backend after scan
        self._blacken_backend(backend)

        return True

    def _report_statistics(self):
        """Report per-detector detection statistics."""
        logger.info("=== Detector Statistics ===")
        for detector_id in range(self.num_detectors):
            total = (
                self.detector_success_counts[detector_id]
                + self.detector_failure_counts[detector_id]
            )
            if total > 0:
                success_rate = self.detector_success_counts[detector_id] / total * 100
                logger.info(
                    f"Detector {detector_id}: {self.detector_success_counts[detector_id]}/{total} "
                    f"({success_rate:.1f}% success rate)"
                )
                if success_rate < 50:
                    logger.warning(
                        f"Detector {detector_id} has low success rate (<50%)! "
                        f"Check camera connection and positioning."
                    )

    def run(self):
        """Main coordinator loop."""
        try:
            logger.info("UnifiedCoordinator starting...")

            # Initialize backend
            backend = self.backend_factory()
            logger.info(f"Backend created: {type(backend).__name__}")

            led_count = backend.get_led_count()
            logger.info(f"LED count: {led_count}")
            self._led_count_queue.put(led_count)

            # Blacken all LEDs initially
            self._blacken_backend(backend)
            logger.info("UnifiedCoordinator initialized and ready")

        except Exception as e:
            logger.error(f"UnifiedCoordinator failed to initialize: {e}")
            import traceback
            traceback.print_exc()
            self._led_count_queue.put(-1)
            return

        # Main loop: wait for scan requests
        while not self._exit_event.is_set():
            try:
                # Check for scan request (non-blocking with timeout)
                try:
                    scan_request = self._scan_request_queue.get(timeout=0.1)
                except:
                    # No request yet, check exit condition
                    continue

                # Unpack scan request
                led_from, led_to, view_id = scan_request

                # Adjust led_to if it exceeds backend capacity
                actual_led_to = min(led_to, led_count)

                # Execute scan
                success = self._run_scan(backend, led_from, actual_led_to, view_id)

                # Report statistics after scan
                if success:
                    self._report_statistics()

            except Exception as e:
                logger.error(f"Error in coordinator loop: {e}")
                import traceback
                traceback.print_exc()

        # Cleanup
        logger.info("UnifiedCoordinator shutting down...")
        self._blacken_backend(backend)
        logger.info("UnifiedCoordinator stopped")
