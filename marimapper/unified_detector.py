"""
UnifiedDetector - DEPRECATED: Compatibility shim for legacy code.

This module is deprecated and maintained only for backwards compatibility.
New code should use `marimapper.pipeline.detection.DetectionWorker` instead.

The UnifiedDetector class is now an alias for DetectionWorker from the
refactored detection package.

Migration guide:
    OLD: from marimapper.unified_detector import UnifiedDetector
    NEW: from marimapper.pipeline.detection import DetectionWorker

The API is fully compatible - simply change the import.
"""

import warnings
from typing import Optional

from marimapper.led import Point2D

# Import the new implementation
from marimapper.pipeline.detection import DetectionWorker

# Show deprecation warning on first import
warnings.warn(
    "marimapper.unified_detector is deprecated. "
    "Use 'from marimapper.pipeline.detection import DetectionWorker' instead. "
    "UnifiedDetector is now an alias for DetectionWorker and will be removed in a future version.",
    DeprecationWarning,
    stacklevel=2,
)


class DetectionResult:
    """
    Result of a single LED detection attempt.

    DEPRECATED: This class is maintained for backwards compatibility only.
    Internal use only - not part of the public API.
    """

    def __init__(self, success: bool, led_id: int, position: Optional[Point2D] = None):
        self.success = success
        self.led_id = led_id
        self.position = position


# Compatibility alias: UnifiedDetector is now DetectionWorker
class UnifiedDetector(DetectionWorker):
    """
    DEPRECATED: Use DetectionWorker instead.

    Single camera detector that responds to coordinator commands.
    Used identically for single-camera or multi-camera setups.

    This class is maintained for backwards compatibility only.
    It inherits all functionality from DetectionWorker.
    """
    pass


# Export the alias
__all__ = ["UnifiedDetector", "DetectionResult"]
