"""
Utilities for serializing and deserializing ScannerArgs objects to/from JSON.

This module handles the conversion of ScannerArgs objects (which contain complex
objects like backend factories and Path objects) into JSON-serializable dictionaries
and back.
"""

import argparse
import inspect
from functools import partial
from pathlib import Path
from typing import Any, Dict, Optional

from marimapper.backends.backend_utils import backend_factories


def serialize_backend_config(backend_factory: partial, backend_type: str) -> Dict[str, Any]:
    """
    Extract backend configuration from a partial backend factory.

    Args:
        backend_factory: Partial object wrapping Backend class
        backend_type: Backend type name (e.g., "artnet", "wled")

    Returns:
        Dictionary with backend type and arguments
    """
    # Get the Backend class from the partial
    backend_class = backend_factory.func

    # Get __init__ signature to extract parameter names
    sig = inspect.signature(backend_class.__init__)
    param_names = list(sig.parameters.keys())[1:]  # Skip 'self'

    # Map positional args to parameter names
    args_dict = {}
    for name, value in zip(param_names, backend_factory.args):
        # Convert Path objects to strings
        if isinstance(value, Path):
            value = str(value)
        args_dict[name] = value

    # Add keyword arguments
    for key, value in backend_factory.keywords.items():
        if isinstance(value, Path):
            value = str(value)
        args_dict[key] = value

    return {
        "type": backend_type,
        "args": args_dict
    }


def deserialize_backend_config(backend_config: Dict[str, Any]) -> tuple[partial, str]:
    """
    Reconstruct backend factory from configuration dictionary.

    Args:
        backend_config: Dictionary with backend type and arguments

    Returns:
        Tuple of (backend_factory partial, backend_type string)

    Raises:
        KeyError: If backend type is not recognized
        ValueError: If backend configuration is invalid
    """
    backend_type = backend_config["type"]
    args_dict = backend_config["args"]

    if backend_type not in backend_factories:
        raise ValueError(f"Unknown backend type: {backend_type}")

    # Create argparse.Namespace with backend args
    args = argparse.Namespace(**args_dict)

    # Add backend type to args (required by factory)
    args.backend = backend_type

    # Call backend factory to create partial
    backend_factory = backend_factories[backend_type](args)

    return backend_factory, backend_type


def serialize_axis_config(axis_config: Optional[Dict[str, str]]) -> Optional[Dict[str, str]]:
    """
    Serialize axis camera configuration.

    Args:
        axis_config: Dictionary with host, username, password

    Returns:
        Same dictionary (already JSON-serializable)
    """
    return axis_config


def deserialize_axis_config(axis_config_data: Optional[Dict[str, str]]) -> Optional[Dict[str, str]]:
    """
    Deserialize axis camera configuration.

    Args:
        axis_config_data: Dictionary with host, username, password

    Returns:
        Same dictionary
    """
    return axis_config_data


def serialize_scanner_args(scanner_args: Any, backend_type: str) -> Dict[str, Any]:
    """
    Convert ScannerArgs object to JSON-serializable dictionary.

    Args:
        scanner_args: ScannerArgs object from gui_cli.py
        backend_type: Backend type string (needed for serialization)

    Returns:
        Dictionary containing all scanner configuration
    """
    # Serialize backend configuration
    backend_config = serialize_backend_config(scanner_args.backend_factory, backend_type)

    config = {
        "backend": backend_config,
        "camera": {
            "device": scanner_args.device,
            "dark_exposure": scanner_args.dark_exposure,
            "threshold": scanner_args.threshold,
            "camera_model": scanner_args.camera_model,
            "axis_config": serialize_axis_config(getattr(scanner_args, 'axis_config', None)),
        },
        "scanner": {
            "led_start": scanner_args.led_start,
            "led_end": scanner_args.led_end,
            "interpolation_max_fill": scanner_args.interpolation_max_fill,
            "interpolation_max_error": scanner_args.interpolation_max_error,
            "check_movement": scanner_args.check_movement,
        }
    }

    return config


def deserialize_scanner_args(config: Dict[str, Any], output_dir: Path) -> Any:
    """
    Reconstruct ScannerArgs object from configuration dictionary.

    Args:
        config: Configuration dictionary from serialize_scanner_args
        output_dir: Output directory for scans (from project)

    Returns:
        ScannerArgs-like object (anonymous class instance)

    Raises:
        ValueError: If configuration is invalid or backend is unknown
    """
    # Deserialize backend
    backend_factory, backend_type = deserialize_backend_config(config["backend"])

    # Extract camera config
    camera_config = config["camera"]

    # Extract scanner config
    scanner_config = config["scanner"]

    # Reconstruct ScannerArgs object (same structure as gui_cli.py)
    class ScannerArgs:
        def __init__(self):
            self.output_dir = Path(output_dir)
            self.device = camera_config["device"]
            self.dark_exposure = camera_config["dark_exposure"]
            self.threshold = camera_config["threshold"]
            self.backend_factory = backend_factory
            self.led_start = scanner_config["led_start"]
            self.led_end = scanner_config["led_end"]
            self.interpolate = scanner_config["interpolation_max_fill"] != -1
            self.interpolation_max_fill = scanner_config["interpolation_max_fill"]
            self.interpolation_max_error = scanner_config["interpolation_max_error"]
            self.check_movement = scanner_config["check_movement"]
            self.camera_model = camera_config["camera_model"]
            self.axis_config = deserialize_axis_config(camera_config.get("axis_config"))

    return ScannerArgs(), backend_type


def get_backend_type_from_args(scanner_args: Any) -> str:
    """
    Extract backend type from ScannerArgs by inspecting the backend factory.

    This is a heuristic approach that looks at the backend factory function name.

    Args:
        scanner_args: ScannerArgs object

    Returns:
        Backend type string (e.g., "artnet", "wled")
    """
    # Try to extract backend type from factory function name
    # Factory functions are named like "artnet_backend_factory"
    factory_func = scanner_args.backend_factory.func
    func_module = factory_func.__module__

    # Extract backend type from module path
    # e.g., "marimapper.backends.artnet.artnet_backend" -> "artnet"
    if "backends" in func_module:
        parts = func_module.split(".")
        backend_index = parts.index("backends") + 1
        if backend_index < len(parts):
            return parts[backend_index]

    # Fallback: try to get from function name
    # e.g., "artnet_backend_factory" -> "artnet"
    func_name = factory_func.__name__
    if "_backend_factory" in func_name:
        return func_name.replace("_backend_factory", "")

    # Last resort: check if backend type is in available backends
    for backend_type in backend_factories.keys():
        if backend_type in func_module.lower() or backend_type in func_name.lower():
            return backend_type

    raise ValueError(f"Could not determine backend type from factory: {factory_func}")
