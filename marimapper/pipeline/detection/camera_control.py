"""
Camera control helpers for detection modes.

This module provides functions to switch camera between:
- Dark mode: Minimal exposure for LED detection
- Preview mode: Default exposure for visual inspection

These functions handle exposure, gain, and autofocus settings.
"""

from multiprocessing import get_logger
from marimapper.camera import Camera

logger = get_logger()


def set_cam_default(cam: Camera) -> None:
    """
    Reset camera to default preview mode.

    Restores camera to default settings for visual inspection:
    - Default exposure (auto or hardware default)
    - Autofocus enabled (if supported)
    - Default gain

    Args:
        cam: Camera instance to configure
    """
    logger.info("Resetting camera to default preview mode")
    cam.reset()
    cam.eat()  # Flush buffered frames after settings change


def set_cam_dark(cam: Camera, exposure: int) -> bool:
    """
    Configure camera for LED detection (dark mode).

    Sets camera to minimal exposure for detecting bright LEDs in dark scenes:
    - Disables autofocus (prevents focus hunting)
    - Sets manual exposure mode
    - Sets minimal gain
    - Applies specified exposure value

    Args:
        cam: Camera instance to configure
        exposure: Exposure value (hardware-specific, typically 1-10 for dark mode)

    Returns:
        True if exposure was successfully set, False otherwise

    Note:
        Some cameras (especially macOS) do not support manual exposure control.
        If exposure control fails, user should darken the scene and adjust threshold instead.
    """
    logger.info(f"Setting camera to dark mode (exposure={exposure})")

    # Disable autofocus to prevent focus hunting during detection
    cam.set_autofocus(0, 0)

    # Set manual exposure mode
    cam.set_exposure_mode(0)

    # Set minimal gain
    cam.set_gain(0)

    # Apply dark exposure setting
    if not cam.set_exposure(exposure):
        logger.warning(
            f"Failed to set exposure to {exposure}. Your camera might not support exposure control. "
            f"Try darkening the scene and adjusting the threshold with --threshold"
        )

    exposure_success = cam.set_exposure(exposure)

    # Flush buffered frames (important: old frames may have wrong exposure)
    cam.eat()

    return exposure_success
