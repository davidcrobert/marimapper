"""
LED backend abstraction layer.

Defines the LedBackend protocol that all LED control backends must implement.
Provides a consistent interface for the scanner to control LEDs regardless
of the underlying hardware (ArtNet, WLED, FadeCandy, PixelBlaze, etc.).
"""

from typing import Protocol, runtime_checkable
import numpy as np


@runtime_checkable
class LedBackend(Protocol):
    """
    Protocol for LED backend implementations.

    All LED backends (ArtNet, WLED, FadeCandy, PixelBlaze, custom) must implement
    this interface to work with the MariMapper scanner.
    """

    def get_led_count(self) -> int:
        """
        Get the total number of controllable LEDs.

        Returns:
            Number of LEDs this backend can control
        """
        ...

    def set_led(self, led_index: int, on: bool) -> None:
        """
        Set a single LED on or off.

        Args:
            led_index: Zero-based LED index
            on: True to turn LED on (white), False to turn off
        """
        ...

    def set_leds(self, buffer: np.ndarray) -> None:
        """
        Set all LEDs at once with RGB color data.

        Optional method for colorful preview of reconstruction quality.
        If not implemented, falls back to set_led() calls.

        Args:
            buffer: Numpy array of shape (led_count, 3) with RGB values (0-255)
        """
        ...


# Re-export existing backend implementations for compatibility
# These will eventually be moved under hardware/led_backends/<backend_name>/
from marimapper.backends.backend_utils import backend_factories, backend_arg_setters

__all__ = [
    "LedBackend",
    "backend_factories",
    "backend_arg_setters",
]
