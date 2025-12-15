"""
Detection command schemas and message types.

This module defines the command protocol for coordinating detection workers.
Commands are sent from coordinators to detector workers via multiprocessing queues.

Command message format: Tuple of (command_type: str, *args)

Example:
    command_queue.put(("DETECT_LED", 42))  # Detect LED with ID 42
    command_queue.put(("CHECK_DARKNESS",))  # Check if scene is dark
    command_queue.put(("EXIT",))  # Shutdown worker
"""

from enum import Enum
from typing import Optional, NamedTuple
from dataclasses import dataclass


class DetectionCommand(str, Enum):
    """
    Commands sent from coordinator to detection workers.
    """
    # Detection commands
    CHECK_DARKNESS = "CHECK_DARKNESS"      # Verify no LED visible (false positive check)
    DETECT_LED = "DETECT_LED"              # Detect specified LED (args: led_id)
    REDETECT_LED = "REDETECT_LED"          # Re-detect for movement check (args: led_id)

    # Camera control commands
    SET_DARK = "SET_DARK"                  # Switch to dark/detection mode
    SET_BRIGHT = "SET_BRIGHT"              # Switch to bright/preview mode
    SET_THRESHOLD = "SET_THRESHOLD"        # Update detection threshold (args: threshold)

    # Configuration commands
    SET_MASK = "SET_MASK"                  # Update detection mask (args: mask_dict)
    APPLY_CONFIG = "APPLY_CONFIG"          # Apply camera config from file (AXIS only)

    # Lifecycle commands
    SCAN_COMPLETE = "SCAN_COMPLETE"        # Notify scan finished
    EXIT = "EXIT"                          # Shutdown worker


class DetectionResult(str, Enum):
    """
    Results sent from detection workers to coordinator.
    """
    # Success results
    DARKNESS_CLEAR = "DARKNESS_CLEAR"      # Darkness check passed
    DETECT_SUCCESS = "DETECT_SUCCESS"      # LED detected (includes position data)
    REDETECT_SUCCESS = "REDETECT_SUCCESS"  # LED re-detected (includes position data)

    # Failure results
    DARKNESS_FAIL = "DARKNESS_FAIL"        # Darkness check failed (LED visible)
    DETECT_FAIL = "DETECT_FAIL"            # LED not detected
    REDETECT_FAIL = "REDETECT_FAIL"        # LED not re-detected

    # Error results
    ERROR = "ERROR"                        # Worker error (includes error message)


@dataclass
class DetectionPosition:
    """
    Result data for successful LED detection.
    """
    led_id: int
    x: float  # Normalized u coordinate [0, 1]
    y: float  # Normalized v coordinate [0, 1]


@dataclass
class MaskData:
    """
    Detection mask configuration.
    """
    mask: Optional[bytes]  # Binary mask data (255 = detect, 0 = ignore), or None to clear
    resolution: Optional[tuple]  # Original mask resolution as (height, width)


def create_command(command: DetectionCommand, *args) -> tuple:
    """
    Create a command message tuple.

    Args:
        command: Command enum value
        *args: Command arguments (if any)

    Returns:
        Command message tuple: (command_type, *args)

    Examples:
        >>> create_command(DetectionCommand.DETECT_LED, 42)
        ("DETECT_LED", 42)

        >>> create_command(DetectionCommand.CHECK_DARKNESS)
        ("CHECK_DARKNESS",)
    """
    return (command.value, *args)


def create_result(result: DetectionResult, camera_id: int, data=None) -> tuple:
    """
    Create a result message tuple.

    Args:
        result: Result enum value
        camera_id: ID of camera that produced this result
        data: Optional result data (e.g., DetectionPosition dict)

    Returns:
        Result message tuple: (result_type, camera_id, data)

    Examples:
        >>> create_result(DetectionResult.DARKNESS_CLEAR, 0)
        ("DARKNESS_CLEAR", 0, None)

        >>> create_result(DetectionResult.DETECT_SUCCESS, 0, {"led_id": 42, "x": 0.5, "y": 0.5})
        ("DETECT_SUCCESS", 0, {"led_id": 42, "x": 0.5, "y": 0.5})
    """
    return (result.value, camera_id, data)
