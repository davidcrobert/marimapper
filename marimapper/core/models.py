"""
Lightweight domain models used across the pipeline.

These dataclasses avoid heavy dependencies so they can be shared by
subprocesses and UI layers alike.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

Vec2 = Tuple[float, float]
Vec3 = Tuple[float, float, float]


@dataclass
class CameraSpec:
    """Camera identity and configuration metadata."""

    name: str
    device: Optional[str] = None  # USB or platform device identifier
    host: Optional[str] = None  # Network host for IP cameras
    username: Optional[str] = None
    password: Optional[str] = None
    model: Optional[str] = None  # Human-readable model string
    focal_length: Optional[float] = None
    fov_degrees: Optional[float] = None


@dataclass
class LedSample2D:
    """Single 2D LED observation in a specific view."""

    led_id: int
    view_id: int
    position: Vec2  # Pixel coordinates
    confidence: float = 1.0
    camera_name: Optional[str] = None
    frame_timestamp: Optional[float] = None  # Seconds since epoch


@dataclass
class Detection:
    """Detection metadata and measurement."""

    led_id: int
    position: Vec2
    confidence: float = 1.0
    view_id: int = 0
    camera_name: Optional[str] = None
    threshold: Optional[int] = None
    frame_timestamp: Optional[float] = None


@dataclass
class DetectionSet:
    """Grouped detections produced during a scan step."""

    led_id: int
    view_id: int
    detections: List[Detection] = field(default_factory=list)
    camera_name: Optional[str] = None


@dataclass
class ScanRequest:
    """Description of a scan task."""

    led_from: int
    led_to: int
    view_id: int
    mask_path: Optional[Path] = None
    movement_check: bool = True
    timeout_seconds: Optional[float] = None


@dataclass
class ScanResult:
    """Aggregated result of a scan request."""

    request: ScanRequest
    detections: List[DetectionSet] = field(default_factory=list)
    cancelled: bool = False
    error: Optional[str] = None


@dataclass
class ReconstructionResult:
    """3D reconstruction outputs and provenance."""

    points: List[Vec3] = field(default_factory=list)
    normals: Optional[List[Vec3]] = None
    metadata: Dict[str, str] = field(default_factory=dict)
    source_views: List[int] = field(default_factory=list)
    output_dir: Optional[Path] = None
