"""
Video source abstractions for different capture methods.

Provides a uniform interface for capturing frames regardless of
underlying implementation (FFmpeg, OpenCV MJPEG, etc.)
"""
from abc import ABC, abstractmethod
from typing import Optional
import numpy as np
import cv2
import logging

logger = logging.getLogger(__name__)


class VideoSource(ABC):
    """Abstract base class for video frame capture."""

    @abstractmethod
    def start(self) -> None:
        """Start video capture."""
        pass

    @abstractmethod
    def read(self) -> np.ndarray:
        """Read a single frame."""
        pass

    @abstractmethod
    def flush(self, count: int = 30) -> None:
        """Discard frames to clear buffer."""
        pass

    @abstractmethod
    def stop(self) -> None:
        """Stop video capture and release resources."""
        pass

    @abstractmethod
    def is_running(self) -> bool:
        """Check if capture is active."""
        pass


class FFmpegVideoSource(VideoSource):
    """Video capture via FFmpeg subprocess (for USB cameras)."""

    def __init__(self, device_identifier: str, width: int = 640, height: int = 360):
        from .ffmpeg_capture import FFmpegCapture
        self._capture = FFmpegCapture(device_identifier, width=width, height=height)
        self._device_identifier = device_identifier

    def start(self) -> None:
        logger.debug(f"Starting FFmpeg video source for {self._device_identifier}")
        self._capture.start()

    def read(self) -> np.ndarray:
        return self._capture.read()

    def flush(self, count: int = 30) -> None:
        self._capture.flush(count)

    def stop(self) -> None:
        logger.debug(f"Stopping FFmpeg video source for {self._device_identifier}")
        self._capture.stop()

    def is_running(self) -> bool:
        return self._capture.is_running()


class MJPEGVideoSource(VideoSource):
    """Video capture via HTTP MJPEG stream (for AXIS cameras)."""

    def __init__(self, host: str, username: str = "root", password: str = ""):
        stream_url = f"http://{username}:{password}@{host}/axis-cgi/mjpg/video.cgi"
        self._stream_url = stream_url
        self._host = host
        self._device: Optional[cv2.VideoCapture] = None

    def start(self) -> None:
        logger.info(f"Connecting to MJPEG stream at {self._host}...")
        self._device = cv2.VideoCapture(self._stream_url)

        if not self._device.isOpened():
            raise RuntimeError(f"Failed to connect to MJPEG stream at {self._host}")

        logger.info(f"Successfully connected to MJPEG stream at {self._host}")

    def read(self) -> np.ndarray:
        if self._device is None:
            raise RuntimeError("MJPEG source not started")

        ret, frame = self._device.read()
        if not ret:
            raise RuntimeError(f"Failed to read from MJPEG stream at {self._host}")

        return frame

    def flush(self, count: int = 30) -> None:
        if self._device is None:
            return

        for _ in range(count):
            self._device.read()

    def stop(self) -> None:
        if self._device is not None:
            logger.debug(f"Releasing MJPEG stream at {self._host}")
            self._device.release()
            self._device = None

    def is_running(self) -> bool:
        return self._device is not None and self._device.isOpened()
