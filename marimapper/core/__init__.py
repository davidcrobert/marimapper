"""
Core domain models and shared message schemas.

This module is intentionally lightweight so it can be imported in
process workers without pulling in heavyweight dependencies.
"""

from .models import (
    Vec2,
    Vec3,
    CameraSpec,
    LedSample2D,
    Detection,
    DetectionSet,
    ScanRequest,
    ScanResult,
    ReconstructionResult,
)
from .events import (
    PipelineStage,
    DetectionCommand,
    DetectionEvent,
    ReconstructionEvent,
)
from .config import (
    CameraVideoConfig,
    CameraControlConfig,
    CameraConfig,
    BackendConfig,
    ScannerConfig,
    MariMapperConfig,
    config_from_argparse,
)

__all__ = [
    "Vec2",
    "Vec3",
    "CameraSpec",
    "LedSample2D",
    "Detection",
    "DetectionSet",
    "ScanRequest",
    "ScanResult",
    "ReconstructionResult",
    "PipelineStage",
    "DetectionCommand",
    "DetectionEvent",
    "ReconstructionEvent",
    "CameraVideoConfig",
    "CameraControlConfig",
    "CameraConfig",
    "BackendConfig",
    "ScannerConfig",
    "MariMapperConfig",
    "config_from_argparse",
]
