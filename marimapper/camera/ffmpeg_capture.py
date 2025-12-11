"""
FFmpeg-based camera frame capture.

Captures frames from USB cameras via FFmpeg subprocess, providing reliable
cross-platform camera access.
"""
import subprocess
import platform
import threading
import queue
import numpy as np
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class FFmpegCapture:
    """
    Captures frames from a camera using FFmpeg subprocess.

    Uses platform-specific FFmpeg commands to capture raw video frames
    and provides them as numpy arrays compatible with OpenCV.
    """

    def __init__(self, device_identifier: str, width: int = 1280, height: int = 720, fps: int = 30):
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

        logger.info(f"FFmpegCapture initialized for {device_identifier} at {width}x{height}@{fps}fps")

    def start(self) -> None:
        """Start the FFmpeg subprocess and begin capturing frames."""
        if self.is_running_flag:
            logger.warning("FFmpeg capture already running")
            return

        cmd = self._build_ffmpeg_command()
        logger.debug(f"Starting FFmpeg: {' '.join(cmd)}")

        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=self.frame_size * 2  # Small buffer: only 2 frames to reduce latency
            )

            # Start background thread to monitor stderr for errors
            self.log_queue = queue.Queue()
            self.log_thread = threading.Thread(
                target=self._monitor_stderr,
                args=(self.process.stderr, self.log_queue),
                daemon=True
            )
            self.log_thread.start()

            self.is_running_flag = True
            logger.info("FFmpeg capture started successfully")

        except FileNotFoundError:
            raise RuntimeError(
                "FFmpeg not found. Please install FFmpeg and add it to your PATH. "
                "Visit https://ffmpeg.org/download.html for installation instructions."
            )
        except Exception as e:
            raise RuntimeError(f"Failed to start FFmpeg capture: {e}")

    def read(self, get_latest: bool = False) -> np.ndarray:
        """
        Read a frame from the camera.

        Args:
            get_latest: If True, drain the buffer and return only the latest frame.
                       This reduces latency but may drop frames.

        Returns:
            BGR frame as numpy array (height, width, 3)

        Raises:
            Exception: If capture is not running or frame read fails
        """
        if not self.is_running_flag or self.process is None:
            raise Exception("FFmpeg capture is not running. Call start() first.")

        # Check for FFmpeg errors
        self._check_for_errors()

        if get_latest:
            # Drain buffer to get latest frame
            return self._read_latest_frame()
        else:
            # Read next available frame
            return self._read_single_frame()

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

    def _read_latest_frame(self) -> np.ndarray:
        """
        Drain the buffer and return only the latest frame.

        This is useful for preview/display to reduce latency.
        """
        import select

        frame = None

        # Keep reading while data is available
        while True:
            # Check if data is available (non-blocking)
            if self.platform == 'Windows':
                # Windows doesn't support select on pipes, just read one frame
                frame = self._read_single_frame()
                break
            else:
                # Linux/Mac: use select to check for data
                readable, _, _ = select.select([self.process.stdout], [], [], 0)
                if readable:
                    frame = self._read_single_frame()
                else:
                    # No more data available
                    break

        if frame is None:
            # No frames available, do blocking read
            frame = self._read_single_frame()

        return frame

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

        if self.process is not None:
            try:
                self.process.terminate()
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                logger.warning("FFmpeg did not terminate gracefully, killing process")
                self.process.kill()
            except Exception as e:
                logger.error(f"Error stopping FFmpeg: {e}")

        self.process = None
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
