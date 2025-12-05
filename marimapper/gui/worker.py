"""
Worker thread for monitoring scanner status and queues.

This thread polls the frame queue and detector update queue to emit
Qt signals for updating the GUI in a thread-safe manner.
"""

import time
from multiprocessing import Queue
from PyQt6.QtCore import QThread
from marimapper.gui.signals import MariMapperSignals
from marimapper.queues import Queue2D, DetectionControlEnum


class StatusMonitorThread(QThread):
    """
    Worker thread that monitors scanner queues and emits Qt signals.

    This thread runs in the background and polls various queues from the
    scanner processes, emitting Qt signals when updates are available.
    """

    def __init__(
        self,
        signals: MariMapperSignals,
        frame_queue: Queue,
        detector_update_queue: Queue2D,
        info_3d_queue=None,
        data_3d_queue=None,
    ):
        """
        Initialize the status monitor thread.

        Args:
            signals: MariMapperSignals object for emitting Qt signals
            frame_queue: Queue containing video frames from detector
            detector_update_queue: Queue2D for detection status updates
            info_3d_queue: Queue3DInfo for 3D reconstruction status updates
            data_3d_queue: Queue3D for full 3D LED data (for visualization)
        """
        super().__init__()
        self.signals = signals
        self.frame_queue = frame_queue
        self.detector_update_queue = detector_update_queue
        self.info_3d_queue = info_3d_queue
        self.data_3d_queue = data_3d_queue
        self.running = True

    def run(self):
        """Main thread loop - polls queues and emits signals."""
        frame_count = 0
        loop_count = 0
        self.signals.log_message.emit("info", "Status monitor thread started")

        while self.running:
            loop_count += 1
            try:
                # Poll frame queue (non-blocking)
                if not self.frame_queue.empty():
                    try:
                        frame = self.frame_queue.get_nowait()
                        frame_count += 1
                        if frame_count <= 3:  # Log first 3 frames
                            self.signals.log_message.emit("info", f"Frame {frame_count} received: shape={frame.shape}")
                        self.signals.frame_ready.emit(frame)
                    except Exception as e:
                        if frame_count == 0:  # Only log if we haven't received any frames yet
                            self.signals.log_message.emit("warning", f"Error getting frame: {e}")
                        pass  # Queue empty, ignore

                # Poll detector update queue (non-blocking)
                if not self.detector_update_queue.empty():
                    try:
                        control, data = self.detector_update_queue.get()

                        if control == DetectionControlEnum.DETECT:
                            # LED detected
                            self.signals.led_detected.emit(data)
                            self.signals.log_message.emit(
                                "info", f"LED {data.led_id} detected at view {data.view_id}"
                            )

                        elif control == DetectionControlEnum.SKIP:
                            # LED skipped (not found)
                            self.signals.led_skipped.emit(data)
                            self.signals.log_message.emit(
                                "warning", f"LED {data} not found, skipping"
                            )

                        elif control == DetectionControlEnum.DONE:
                            # Scan completed successfully
                            view_id = data
                            self.signals.scan_completed.emit(view_id)
                            self.signals.log_message.emit(
                                "success", f"View {view_id} scan completed successfully"
                            )

                        elif control == DetectionControlEnum.FAIL:
                            # Scan failed
                            self.signals.scan_failed.emit("Detection failed - LED visible when all should be off")
                            self.signals.log_message.emit(
                                "error", "Scan failed - LED visible when all should be off"
                            )

                        elif control == DetectionControlEnum.DELETE:
                            # View deleted due to camera movement
                            view_id = data
                            self.signals.view_deleted.emit(view_id)
                            self.signals.log_message.emit(
                                "warning", f"View {view_id} deleted due to camera movement"
                            )

                    except:
                        pass  # Queue empty or other error, ignore

                # Poll 3D info queue for reconstruction status updates
                if self.info_3d_queue is not None and not self.info_3d_queue.empty():
                    try:
                        led_info_dict = self.info_3d_queue.get_nowait()
                        self.signals.log_message.emit("info", f"Received 3D info update: {len(led_info_dict)} LEDs")
                        self.signals.reconstruction_updated.emit(led_info_dict)
                    except Exception as e:
                        self.signals.log_message.emit("warning", f"Error reading 3D info queue: {e}")
                        pass  # Queue empty, ignore

                # Poll 3D data queue for full 3D visualization
                if self.data_3d_queue is not None and not self.data_3d_queue.empty():
                    try:
                        leds_3d = self.data_3d_queue.get_nowait()
                        if len(leds_3d) > 0:
                            self.signals.log_message.emit("info", f"Received 3D data update: {len(leds_3d)} LEDs")
                            self.signals.points_3d_updated.emit(leds_3d)
                    except Exception as e:
                        self.signals.log_message.emit("warning", f"Error reading 3D data queue: {e}")
                        pass  # Queue empty, ignore

                # Periodic diagnostic log (every 3 seconds, ~90 loops at 30Hz)
                if loop_count == 90 and frame_count == 0:
                    self.signals.log_message.emit("warning",
                        f"No frames received yet. Queue empty: {self.frame_queue.empty()}")

                # Sleep briefly to avoid busy-waiting
                time.sleep(0.033)  # ~30 Hz polling rate

            except Exception as e:
                self.signals.log_message.emit("error", f"Monitor thread error: {str(e)}")
                time.sleep(0.1)

    def stop(self):
        """Stop the monitoring thread."""
        self.running = False
