"""
Shared enums and event payloads for interprocess communication.

Keeps message schemas centralized to reduce ad-hoc tuples across the codebase.
"""
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

from .models import DetectionSet, ReconstructionResult, ScanRequest


class PipelineStage(Enum):
    """High-level pipeline phases for status reporting."""

    IDLE = auto()
    SCANNING = auto()
    RECONSTRUCTING = auto()
    ERROR = auto()


class DetectionCommand(Enum):
    """Commands issued to detector workers."""

    START_SCAN = auto()
    CANCEL_SCAN = auto()
    SET_THRESHOLD = auto()
    SET_MASK = auto()
    SET_EXPOSURE = auto()
    SHUTDOWN = auto()


@dataclass
class DetectionEvent:
    """Event emitted by detector workers."""

    request: ScanRequest
    result: DetectionSet
    cancelled: bool = False
    error: Optional[str] = None


@dataclass
class ReconstructionEvent:
    """Event emitted by reconstruction stage."""

    stage: PipelineStage
    result: Optional[ReconstructionResult] = None
    error: Optional[str] = None
