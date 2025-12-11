"""
FFmpeg-based camera frame capture.

Captures frames from USB cameras via FFmpeg subprocess, providing reliable
cross-platform camera access.
"""
import subprocess
import platform
import threading
import queue
import time
import numpy as np
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class FFmpegCapture:
    """
    Captures frames from a camera using FFmpeg subprocess.

    Uses platform-specific FFmpeg commands to capture raw video frames
    and provides them as numpy arrays compatible with OpenCV.

    Uses a background reader thread to continuously capture frames and
    maintain only the latest frame, ensuring low-latency preview on all platforms.
    """

    def __init__(self, device_identifier: str, width: int = 640, height: int = 360, fps: int = 30):
        """
        Initialize FFmpeg capture.

        Args:
            device_identifier: Platform-specific device identifier
                             (e.g., "22_Cam2" for Windows, "/dev/video0" for Linux)
            width: Frame width in pixels
            height: Frame height in pixels
            fps: Frames per second
        """
        self.device_identifier = device_identifier
        self.width = width
        self.height = height
        self.fps = fps
        self.platform = platform.system()

        # Calculate frame size in bytes (BGR24 format)
        self.frame_size = width * height * 3

        self.process: Optional[subprocess.Popen] = None
        self.log_queue: Optional[queue.Queue] = None
        self.log_thread: Optional[threading.Thread] = None
        self.is_running_flag = False

        # Background reader thread for low-latency capture
        self._reader_thread: Optional[threading.Thread] = None
        self._latest_frame: Optional[np.ndarray] = None
        self._frame_lock = threading.Lock()
        self._frame_event = threading.Event()  # Signals when new frame is available
        self._stop_reader = threading.Event()

        logger.info(f"FFmpegCapture initialized for {device_identifier} at {width}x{height}@{fps}fps")

    def start(self) -> None:
        """Start the FFmpeg subprocess and begin capturing frames."""
        if self.is_running_flag:
            logger.warning("FFmpeg capture already running")
            return

        cmd = self._build_ffmpeg_command()
        logger.debug(f"Starting FFmpeg: {' '.join(cmd)}")

        try:
            # Use large buffer to prevent FFmpeg from blocking
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=100 * 1024 * 1024  # 100MB buffer like ffmpeg_runner.py
            )

            # Start background thread to monitor stderr for errors
            self.log_queue = queue.Queue()
            self.log_thread = threading.Thread(
                target=self._monitor_stderr,
                args=(self.process.stderr, self.log_queue),
                daemon=True
            )
            self.log_thread.start()

            # Start background reader thread for low-latency frame capture
            self._stop_reader.clear()
            self._reader_thread = threading.Thread(
                target=self._background_reader,
                daemon=True
            )
            self._reader_thread.start()

            # Wait for first frame to ensure capture is working
            if not self._frame_event.wait(timeout=5.0):
                raise RuntimeError("Timeout waiting for first frame from FFmpeg")

            self.is_running_flag = True
            logger.info("FFmpeg capture started successfully")

        except FileNotFoundError:
            raise RuntimeError(
                "FFmpeg not found. Please install FFmpeg and add it to your PATH. "
                "Visit https://ffmpeg.org/download.html for installation instructions."
            )
        except Exception as e:
            raise RuntimeError(f"Failed to start FFmpeg capture: {e}")

    def read(self, get_latest: bool = True) -> np.ndarray:
        """
        Read a frame from the camera.

        Args:
            get_latest: Kept for API compatibility, but now always returns
                       the latest frame (no lag). Default changed to True.

        Returns:
            BGR frame as numpy array (height, width, 3)

        Raises:
            Exception: If capture is not running or frame read fails
        """
        if not self.is_running_flag or self.process is None:
            raise Exception("FFmpeg capture is not running. Call start() first.")

        # Check for FFmpeg errors
        self._check_for_errors()

        # Always return the latest frame from background reader
        return self._get_latest_frame()

    def _read_single_frame(self) -> np.ndarray:
        """Read a single frame from the buffer."""
        # Read exact frame size from stdout
        try:
            raw_bytes = self.process.stdout.read(self.frame_size)
        except Exception as e:
            raise Exception(f"Failed to read from FFmpeg stdout: {e}")

        # Validate frame size
        if len(raw_bytes) == 0:
            raise Exception("FFmpeg pipe closed. Process may have terminated.")

        if len(raw_bytes) != self.frame_size:
            raise Exception(
                f"Incomplete frame: read {len(raw_bytes)} bytes, expected {self.frame_size}. "
                "This may indicate camera disconnection or FFmpeg error."
            )

        # Convert bytes to numpy array
        frame = np.frombuffer(raw_bytes, dtype=np.uint8).reshape((self.height, self.width, 3))
        return frame

    def _background_reader(self) -> None:
        """
        Background thread that continuously reads frames from FFmpeg.

        Maintains only the latest frame for low-latency access.
        This approach works on all platforms including Windows.
        """
        logger.debug("Background reader thread started")
        frames_read = 0

        while not self._stop_reader.is_set():
            try:
                # Read frame from FFmpeg (blocking)
                raw_bytes = self.process.stdout.read(self.frame_size)

                if len(raw_bytes) == 0:
                    logger.warning("FFmpeg pipe closed in background reader")
                    break

                if len(raw_bytes) != self.frame_size:
                    logger.warning(f"Incomplete frame in background reader: {len(raw_bytes)}/{self.frame_size}")
                    continue

                # Convert to numpy array
                frame = np.frombuffer(raw_bytes, dtype=np.uint8).reshape(
                    (self.height, self.width, 3)
                )

                # Store as latest frame (thread-safe)
                with self._frame_lock:
                    self._latest_frame = frame

                # Signal that a frame is available
                self._frame_event.set()

                frames_read += 1
                if frames_read == 1:
                    logger.debug("First frame captured by background reader")

            except Exception as e:
                if not self._stop_reader.is_set():
                    logger.error(f"Background reader error: {e}")
                break

        logger.debug(f"Background reader thread stopped after {frames_read} frames")

    def _get_latest_frame(self) -> np.ndarray:
        """
        Get the latest frame captured by the background reader.

        Returns:
            BGR frame as numpy array (height, width, 3)

        Raises:
            Exception: If no frame is available
        """
        # Wait briefly for a frame if none available
        if not self._frame_event.wait(timeout=1.0):
            raise Exception("Timeout waiting for frame from background reader")

        with self._frame_lock:
            if self._latest_frame is None:
                raise Exception("No frame available from background reader")
            # Return frame directly - no copy needed for display-only use
            # The background reader writes to a new array each time, so this is safe
            return self._latest_frame

    def flush(self, count: int = 30) -> None:
        """
        Discard frames to clear the internal buffer.

        This is important after changing camera settings to ensure
        fresh frames reflect the new settings.

        For efficiency, this restarts the FFmpeg subprocess instead of
        reading frames one by one.

        Args:
            count: Number of frames to discard (parameter kept for compatibility,
                  but restart is more efficient)
        """
        logger.debug(f"Flushing buffer by restarting FFmpeg capture")

        # Restart is more efficient than reading frames one by one
        self.stop()
        self.start()

    def stop(self) -> None:
        """Stop the FFmpeg subprocess and clean up resources."""
        if not self.is_running_flag:
            return

        logger.info("Stopping FFmpeg capture")
        self.is_running_flag = False

        # Signal background reader to stop
        self._stop_reader.set()

        if self.process is not None:
            try:
                self.process.terminate()
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                logger.warning("FFmpeg did not terminate gracefully, killing process")
                self.process.kill()
            except Exception as e:
                logger.error(f"Error stopping FFmpeg: {e}")

        # Wait for reader thread to finish
        if self._reader_thread is not None and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=1.0)

        # Reset state
        self.process = None
        self._reader_thread = None
        self._latest_frame = None
        self._frame_event.clear()

        logger.info("FFmpeg capture stopped")

    def is_running(self) -> bool:
        """Check if capture is currently active."""
        return self.is_running_flag

    def _build_ffmpeg_command(self) -> list:
        """Build platform-specific FFmpeg command with low-latency settings."""
        cmd = ['ffmpeg', '-hide_banner', '-loglevel', 'error']

        if self.platform == 'Linux':
            # Linux uses video4linux2
            cmd.extend(['-f', 'v4l2'])
            cmd.extend(['-input_format', 'mjpeg'])  # MJPEG often more reliable for USB cameras
            cmd.extend(['-framerate', str(self.fps)])
            cmd.extend(['-video_size', f'{self.width}x{self.height}'])
            cmd.extend(['-i', self.device_identifier])

        elif self.platform == 'Darwin':
            # macOS uses avfoundation
            cmd.extend(['-f', 'avfoundation'])
            cmd.extend(['-framerate', str(self.fps)])
            cmd.extend(['-video_size', f'{self.width}x{self.height}'])
            cmd.extend(['-i', self.device_identifier])

        elif self.platform == 'Windows':
            # Windows uses dshow with larger real-time buffer
            cmd.extend(['-f', 'dshow'])
            cmd.extend(['-rtbufsize', '100M'])  # Increase buffer to prevent drops
            cmd.extend(['-framerate', str(self.fps)])
            cmd.extend(['-video_size', f'{self.width}x{self.height}'])
            cmd.extend(['-i', f'video={self.device_identifier}'])

        else:
            raise RuntimeError(f"Unsupported platform: {self.platform}")

        # Low-latency output parameters
        cmd.extend(['-fflags', 'nobuffer'])  # Disable buffering for low latency
        cmd.extend(['-flags', 'low_delay'])  # Optimize for low latency
        cmd.extend(['-f', 'image2pipe'])
        cmd.extend(['-pix_fmt', 'bgr24'])  # OpenCV uses BGR format
        cmd.extend(['-vcodec', 'rawvideo'])
        cmd.extend(['-'])  # Output to pipe (stdout)

        return cmd

    def _monitor_stderr(self, stderr, log_queue):
        """
        Monitor FFmpeg stderr in background thread.

        Reads lines from stderr and adds them to queue for error checking.
        """
        try:
            for line in iter(stderr.readline, b''):
                log_queue.put(line)
        except Exception as e:
            logger.debug(f"stderr monitoring thread ended: {e}")
        finally:
            stderr.close()

    def _check_for_errors(self):
        """Check for FFmpeg errors in the log queue."""
        if self.log_queue is None:
            return

        try:
            while True:
                line = self.log_queue.get_nowait()
                error_msg = line.decode('utf-8', errors='replace').strip()
                if error_msg:
                    logger.error(f"FFmpeg: {error_msg}")
        except queue.Empty:
            pass

    def __del__(self):
        """Cleanup on deletion."""
        if self.is_running_flag:
            self.stop()
