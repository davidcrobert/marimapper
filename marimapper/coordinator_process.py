"""
CoordinatorProcess - Coordinates multi-camera LED detection.

This process is responsible for:
1. Controlling the LED backend (turning LEDs on/off)
2. Synchronizing detection across multiple cameras
3. Collecting and aggregating results from all cameras
4. Managing timeouts and failures

The coordinator sends commands to DetectorWorkerProcesses and waits
for their responses before moving to the next LED.
"""

from multiprocessing import Process, Queue, Event, get_logger
import time
from functools import partial
from typing import Dict, List, Tuple, Optional

logger = get_logger()


class CoordinatorProcess(Process):
    """
    Coordinates multi-camera LED detection by controlling the backend
    and synchronizing detection across multiple camera workers.
    """

    def __init__(
        self,
        backend_factory: partial,
        num_cameras: int,
        led_start: int,
        led_end: int,
        detection_timeout: float = 5.0,
        led_stabilization_delay: float = 0.05,
    ):
        """
        Initialize the coordinator process.

        Args:
            backend_factory: Factory function to create LED backend instance
            num_cameras: Number of camera workers to coordinate
            led_start: First LED index to scan
            led_end: Last LED index to scan (exclusive)
            detection_timeout: Max time to wait for all cameras (seconds)
            led_stabilization_delay: Time to wait after turning LED on (seconds)
        """
        super().__init__()
        self.backend_factory = backend_factory
        self.num_cameras = num_cameras
        self.led_start = led_start
        self.led_end = led_end
        self.detection_timeout = detection_timeout
        self.led_stabilization_delay = led_stabilization_delay

        # Communication queues
        self._command_queues: Dict[int, Queue] = {}  # camera_id -> command queue
        self._result_queue = Queue()  # Shared queue for all worker results
        self._led_count_queue = Queue()  # For returning LED count to Scanner
        self._start_scan_queue = Queue()  # Signal to start scanning
        self._scan_done_event = Event()  # Signal that scan is complete
        self._exit_event = Event()  # Signal to exit process

        # Initialize command queues for each camera
        for camera_id in range(num_cameras):
            self._command_queues[camera_id] = Queue()
            self._command_queues[camera_id].cancel_join_thread()

        self._result_queue.cancel_join_thread()
        self._led_count_queue.cancel_join_thread()
        self._start_scan_queue.cancel_join_thread()

        # Statistics tracking
        self.camera_success_counts: Dict[int, int] = {i: 0 for i in range(num_cameras)}
        self.camera_failure_counts: Dict[int, int] = {i: 0 for i in range(num_cameras)}

    def get_command_queue(self, camera_id: int) -> Queue:
        """Get the command queue for a specific camera."""
        return self._command_queues[camera_id]

    def get_result_queue(self) -> Queue:
        """Get the result queue (shared by all cameras)."""
        return self._result_queue

    def get_led_count(self) -> int:
        """Get LED count from backend (blocks until available)."""
        return self._led_count_queue.get()

    def start_scan(self):
        """Signal the coordinator to start scanning."""
        self._start_scan_queue.put(True)

    def wait_for_scan_complete(self):
        """Block until scan is complete."""
        self._scan_done_event.wait()

    def stop(self):
        """Signal coordinator to exit."""
        self._exit_event.set()

    def _blacken_backend(self, backend) -> bool:
        """Turn off all LEDs."""
        buffer = [[0, 0, 0] for _ in range(backend.get_led_count())]
        try:
            backend.set_leds(buffer)
            return True
        except AttributeError:
            # Backend doesn't support set_leds, turn off LEDs individually
            for led_id in range(backend.get_led_count()):
                backend.set_led(led_id, False)
            return True
        except Exception as e:
            logger.warning(f"Failed to blacken backend: {e}")
            return False

    def _wait_for_all_results(
        self, led_id: int
    ) -> Dict[int, Tuple[bool, Optional[float], Optional[float]]]:
        """
        Wait for all cameras to report results for the current LED.

        Returns:
            Dict mapping camera_id -> (success, x, y)
        """
        results = {}
        timeout_time = time.time() + self.detection_timeout

        while len(results) < self.num_cameras:
            remaining_time = timeout_time - time.time()
            if remaining_time <= 0:
                # Timeout - log which cameras didn't respond
                missing = set(range(self.num_cameras)) - set(results.keys())
                logger.warning(
                    f"LED {led_id}: Timeout waiting for cameras {missing}. "
                    f"Received {len(results)}/{self.num_cameras} responses."
                )
                break

            try:
                msg = self._result_queue.get(timeout=min(0.1, max(0.001, remaining_time)))
                msg_type = msg[0]

                if msg_type == "RESULT":
                    _, camera_id, led_id_recv, success, x, y = msg
                    if led_id_recv == led_id:
                        results[camera_id] = (success, x, y)
                        # Track statistics
                        if success:
                            self.camera_success_counts[camera_id] += 1
                        else:
                            self.camera_failure_counts[camera_id] += 1
                    else:
                        logger.warning(
                            f"Camera {camera_id} returned result for LED {led_id_recv}, "
                            f"expected LED {led_id}"
                        )

                elif msg_type == "ERROR":
                    _, camera_id, error_msg = msg
                    logger.error(f"Camera {camera_id} error: {error_msg}")
                    # Count as failure
                    results[camera_id] = (False, None, None)
                    self.camera_failure_counts[camera_id] += 1

            except Exception:
                # Queue timeout, continue waiting
                continue

        return results

    def _detect_led_synchronized(self, backend, led_id: int) -> bool:
        """
        Coordinate detection of a single LED across all cameras.

        Returns:
            True if at least one camera detected the LED, False otherwise
        """
        # Turn on LED
        backend.set_led(led_id, True)

        # Wait for LED to stabilize
        if self.led_stabilization_delay > 0:
            time.sleep(self.led_stabilization_delay)

        # Broadcast DETECT_LED command to all workers
        for camera_id, cmd_queue in self._command_queues.items():
            try:
                cmd_queue.put(("DETECT_LED", led_id), timeout=1.0)
            except Exception as e:
                logger.error(f"Failed to send DETECT_LED to camera {camera_id}: {e}")

        # Wait for all results
        results = self._wait_for_all_results(led_id)

        # Turn off LED
        backend.set_led(led_id, False)

        # Log results
        successful = sum(1 for success, _, _ in results.values() if success)
        logger.debug(f"LED {led_id}: {successful}/{self.num_cameras} cameras detected")

        return successful > 0

    def _send_scan_complete(self):
        """Notify all workers that scan is complete."""
        for camera_id, cmd_queue in self._command_queues.items():
            try:
                cmd_queue.put(("SCAN_COMPLETE",), timeout=1.0)
            except Exception as e:
                logger.error(f"Failed to send SCAN_COMPLETE to camera {camera_id}: {e}")

    def _report_statistics(self):
        """Report per-camera detection statistics."""
        logger.info("=== Multi-Camera Detection Statistics ===")
        for camera_id in range(self.num_cameras):
            total = (
                self.camera_success_counts[camera_id]
                + self.camera_failure_counts[camera_id]
            )
            if total > 0:
                success_rate = (
                    self.camera_success_counts[camera_id] / total * 100
                )
                logger.info(
                    f"Camera {camera_id}: {self.camera_success_counts[camera_id]}/{total} "
                    f"({success_rate:.1f}% success rate)"
                )
                if success_rate < 50:
                    logger.warning(
                        f"Camera {camera_id} has low success rate (<50%)! "
                        f"Check camera connection and positioning."
                    )

    def run(self):
        """Main coordinator loop."""
        try:
            logger.info("CoordinatorProcess starting...")

            # Initialize backend
            backend = self.backend_factory()
            logger.info(f"Backend created: {type(backend).__name__}")

            led_count = backend.get_led_count()
            logger.info(f"LED count: {led_count}")
            self._led_count_queue.put(led_count)

            # Adjust led_end if it exceeds backend capacity
            actual_led_end = min(self.led_end, led_count)
            if actual_led_end != self.led_end:
                logger.info(
                    f"Adjusted led_end from {self.led_end} to {actual_led_end} "
                    f"(backend max: {led_count})"
                )

            # Blacken all LEDs initially
            self._blacken_backend(backend)
            logger.info("CoordinatorProcess initialized and waiting for scan start")

        except Exception as e:
            logger.error(f"CoordinatorProcess failed to initialize: {e}")
            import traceback
            traceback.print_exc()
            self._led_count_queue.put(-1)
            return

        # Wait for scan start signal or exit
        while not self._exit_event.is_set():
            try:
                # Check for start signal (non-blocking with timeout)
                start_signal = self._start_scan_queue.get(timeout=0.1)
                if start_signal:
                    break
            except Exception:
                # No start signal yet, check exit condition
                continue

        if self._exit_event.is_set():
            logger.info("CoordinatorProcess exiting before scan started")
            self._blacken_backend(backend)
            return

        # Execute scan
        try:
            logger.info(
                f"Starting coordinated scan: LEDs {self.led_start} to {actual_led_end - 1}"
            )

            for led_id in range(self.led_start, actual_led_end):
                if self._exit_event.is_set():
                    logger.info(f"Scan interrupted at LED {led_id}")
                    break

                self._detect_led_synchronized(backend, led_id)

            # Send completion signal to all workers
            self._send_scan_complete()

            # Report statistics
            self._report_statistics()

            # Signal scan complete
            self._scan_done_event.set()
            logger.info("Coordinated scan complete")

        except Exception as e:
            logger.error(f"Error during coordinated scan: {e}")
            import traceback
            traceback.print_exc()
            self._send_scan_complete()
            self._scan_done_event.set()

        finally:
            # Cleanup
            logger.info("CoordinatorProcess cleaning up...")
            self._blacken_backend(backend)
            logger.info("CoordinatorProcess stopped")
