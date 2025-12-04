import warnings

warnings.simplefilter(
    "ignore", UserWarning
)  # see https://github.com/TheMariday/marimapper/issues/78

import multiprocessing
import argparse
import logging
from marimapper.scripts.arg_tools import (
    parse_common_args,
    add_common_args,
    add_camera_args,
    add_scanner_args,
    add_all_backend_parsers,
)
from marimapper.backends.backend_utils import backend_factories
from marimapper.scanner import Scanner
import os


def main():

    logger = multiprocessing.log_to_stderr()
    logger.setLevel(level=logging.WARNING)

    parser = argparse.ArgumentParser(
        description="Marimapper! Scan LEDs in 3D space using your webcam",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        usage=argparse.SUPPRESS,
    )

    for backend_parser in add_all_backend_parsers(parser) + [parser]:
        add_common_args(backend_parser)
        add_camera_args(backend_parser)
        add_scanner_args(backend_parser)

    args = parser.parse_args()

    parse_common_args(args, logger)

    if not os.path.isdir(args.dir):
        raise Exception(f"path {args.dir} does not exist")

    if args.start > args.end:
        raise Exception(f"Start point {args.start} is greater the end point {args.end}")

    backend_factory = backend_factories[args.backend](args)

    # Build camera configuration
    axis_config = None
    axis_configs = None

    if args.axis_cameras_json:
        # Multi-camera mode with JSON config
        import json
        try:
            axis_configs = json.loads(args.axis_cameras_json)
            if not isinstance(axis_configs, list):
                raise Exception("--axis-cameras-json must be a JSON array")
            # Validate and set defaults
            for cfg in axis_configs:
                if 'host' not in cfg:
                    raise Exception("Each camera config must have 'host' field")
                cfg.setdefault('username', 'root')
                cfg.setdefault('password', '')
            logger.info(f"Multi-camera mode: {len(axis_configs)} cameras configured from JSON")
        except json.JSONDecodeError as e:
            raise Exception(f"Invalid JSON in --axis-cameras-json: {e}")

    elif args.axis_hosts:
        # Multi-camera mode with simple comma-separated hosts
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
        logger.info(f"Multi-camera mode: {len(axis_configs)} cameras configured from --axis-hosts")

    elif args.axis_host:
        # Single camera mode (existing behavior)
        if not args.axis_password:
            raise Exception("--axis-password is required when using --axis-host")
        axis_config = {
            'host': args.axis_host,
            'username': args.axis_username,
            'password': args.axis_password,
        }
        logger.info(f"Single camera mode: Axis camera at {args.axis_host}")

    # Create scanner with appropriate config
    scanner = Scanner(
        args.dir,
        args.device,
        args.exposure,
        args.threshold,
        backend_factory,
        args.start,
        args.end,
        args.interpolation_max_fill if args.interpolation_max_fill != -1 else 10000,
        args.interpolation_max_error if args.interpolation_max_error != -1 else 10000,
        args.disable_movement_check,
        args.camera_model,
        axis_config=axis_config,
        axis_configs=axis_configs,
    )

    scanner.mainloop()
    scanner.close()


if __name__ == "__main__":
    main()
