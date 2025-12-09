"""
GUI entry point for MariMapper.

Launches the PyQt6 GUI application for LED mapping.
"""

import warnings

warnings.simplefilter(
    "ignore", UserWarning
)  # see https://github.com/TheMariday/marimapper/issues/78

import multiprocessing
import argparse
import logging
import sys
import os
from pathlib import Path

# CRITICAL: Set multiprocessing start method BEFORE importing PyQt6
# This is required for Open3D compatibility on Linux
if __name__ == "__main__":
    multiprocessing.set_start_method("spawn", force=True)

from PyQt6.QtWidgets import QApplication
from marimapper.scripts.arg_tools import (
    parse_common_args,
    add_common_args,
    add_camera_args,
    add_scanner_args,
    add_all_backend_parsers,
)
from marimapper.backends.backend_utils import backend_factories
from marimapper.gui.main_window import MainWindow


def main():
    """Main entry point for MariMapper GUI."""

    logger = multiprocessing.log_to_stderr()
    logger.setLevel(level=logging.INFO)  # Set to INFO to see detector process logs

    parser = argparse.ArgumentParser(
        description="MariMapper GUI - Scan LEDs in 3D space using your webcam",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        usage=argparse.SUPPRESS,
    )

    # Add backend parsers and common arguments
    for backend_parser in add_all_backend_parsers(parser) + [parser]:
        add_common_args(backend_parser)
        add_camera_args(backend_parser)
        add_scanner_args(backend_parser)

    args = parser.parse_args()

    parse_common_args(args, logger)

    # Validate arguments
    if not os.path.isdir(args.dir):
        raise Exception(f"path {args.dir} does not exist")

    if args.start > args.end:
        raise Exception(f"Start point {args.start} is greater than the end point {args.end}")

    # Create backend factory
    backend_factory = backend_factories[args.backend](args)

    # Build axis_config if axis-host is specified
    axis_config = None
    if args.axis_host:
        if not args.axis_password:
            raise Exception("--axis-password is required when using --axis-host")
        axis_config = {
            'host': args.axis_host,
            'username': args.axis_username,
            'password': args.axis_password,
        }

    # Multi-camera configuration
    axis_configs = None

    if args.axis_cameras_json:
        import json
        try:
            axis_configs = json.loads(args.axis_cameras_json)
            if not isinstance(axis_configs, list):
                raise Exception("--axis-cameras-json must be a JSON array")

            # Validate and set defaults for each camera
            for cfg in axis_configs:
                if 'host' not in cfg:
                    raise Exception("Each camera config must have 'host' field")
                cfg.setdefault('username', 'root')
                cfg.setdefault('password', '')
        except json.JSONDecodeError as e:
            raise Exception(f"Invalid JSON in --axis-cameras-json: {e}")

    elif args.axis_hosts:
        # Simple multi-camera: comma-separated hosts with shared credentials
        hosts = [h.strip() for h in args.axis_hosts.split(',') if h.strip()]
        if len(hosts) == 0:
            raise Exception("--axis-hosts must contain at least one host")
        if not args.axis_password:
            raise Exception("--axis-password is required when using --axis-hosts")

        axis_configs = [
            {
                'host': host,
                'username': args.axis_username,
                'password': args.axis_password,
            }
            for host in hosts
        ]

    # Validate camera count
    if axis_configs is not None and len(axis_configs) > 9:
        raise Exception(f"GUI supports maximum 9 cameras (you provided {len(axis_configs)})")

    # Create scanner args object that MainWindow expects
    class ScannerArgs:
        def __init__(self):
            self.output_dir = Path(args.dir)
            self.device = args.device
            self.dark_exposure = args.exposure
            self.threshold = args.threshold
            self.backend_factory = backend_factory
            self.led_start = args.start
            self.led_end = args.end
            self.interpolate = args.interpolation_max_fill != -1
            self.interpolation_max_fill = args.interpolation_max_fill if args.interpolation_max_fill != -1 else 10000
            self.interpolation_max_error = args.interpolation_max_error if args.interpolation_max_error != -1 else 10000
            self.check_movement = not args.disable_movement_check
            self.camera_model = args.camera_model
            self.axis_config = axis_config
            self.axis_configs = axis_configs

    scanner_args = ScannerArgs()

    # Create Qt Application
    app = QApplication(sys.argv)
    app.setApplicationName("MariMapper")
    app.setOrganizationName("MariMapper")

    # Create and show main window
    window = MainWindow(scanner_args)
    window.show()

    # Run Qt event loop
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
