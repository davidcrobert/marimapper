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
    parse_resolution,
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

    # Handle --list-cameras
    if args.list_cameras:
        from marimapper.camera import list_available_cameras
        cameras = list_available_cameras()
        if len(cameras) == 0:
            print("No cameras found")
        else:
            print("Available cameras:")
            for i, cam in enumerate(cameras, 1):
                print(f"  {i}. {cam.name}")
        return

    if not os.path.isdir(args.dir):
        raise Exception(f"path {args.dir} does not exist")

    if args.start > args.end:
        raise Exception(f"Start point {args.start} is greater the end point {args.end}")

    backend_factory = backend_factories[args.backend](args)

    # Build camera configuration
    axis_config = None
    camera_configs = None
    parsed_camera_configs = None  # List[CameraConfig] from new config file

    def _normalize_camera_cfg(cfg):
        if not isinstance(cfg, dict):
            raise Exception("Each camera config must be an object")
        if "host" in cfg:
            cfg = dict(cfg)
            cfg.setdefault("username", "root")
            cfg.setdefault("password", "")
            return {"host": cfg["host"], "username": cfg["username"], "password": cfg["password"]}
        if "device" in cfg:
            # Device can now be a string (device name) or integer (for compatibility)
            device_name = str(cfg["device"])
            return {"device": device_name}
        raise Exception("Camera config must include either 'host' (Axis) or 'device' (USB)")

    def _parse_json_list(raw_json: str):
        import json
        try:
            cfgs = json.loads(raw_json)
        except json.JSONDecodeError as e:
            raise Exception(f"Invalid JSON in camera configs: {e}")
        if not isinstance(cfgs, list):
            raise Exception("Camera configs JSON must be an array")
        return [_normalize_camera_cfg(cfg) for cfg in cfgs]

    if args.camera_config:
        # NEW: Parse JSON config file (highest priority)
        from marimapper.camera.camera_config import parse_camera_config_file
        try:
            parsed_camera_configs = parse_camera_config_file(args.camera_config)
            logger.info(f"Loaded {len(parsed_camera_configs)} cameras from {args.camera_config}")
        except FileNotFoundError as e:
            raise Exception(str(e))
        except ValueError as e:
            raise Exception(f"Invalid camera config file: {e}")

    elif args.axis_cameras_json:
        # Multi-camera mode with JSON config (Axis or USB/mixed)
        camera_configs = _parse_json_list(args.axis_cameras_json)
        logger.info(f"Multi-camera mode: {len(camera_configs)} cameras configured from JSON")

    elif args.camera_configs_json:
        camera_configs = _parse_json_list(args.camera_configs_json)
        logger.info(f"Multi-camera mode: {len(camera_configs)} cameras configured from JSON")

    elif args.axis_hosts:
        # Multi-camera mode with simple comma-separated hosts
        hosts = [h.strip() for h in args.axis_hosts.split(',') if h.strip()]
        if len(hosts) == 0:
            raise Exception("--axis-hosts must contain at least one host")
        if not args.axis_password:
            raise Exception("--axis-password is required when using --axis-hosts")

        camera_configs = [
            {
                'host': host,
                'username': args.axis_username,
                'password': args.axis_password,
            }
            for host in hosts
        ]
        logger.info(f"Multi-camera mode: {len(camera_configs)} cameras configured from --axis-hosts")

    elif args.devices:
        # Parse device names (strings)
        device_names = [d.strip() for d in args.devices.split(',') if d.strip()]
        if len(device_names) == 0:
            raise Exception("--devices must contain at least one device name")
        # Parse resolution for USB cameras
        width, height = parse_resolution(args.resolution)
        camera_configs = [{"device": d, "width": width, "height": height} for d in device_names]
        logger.info(f"Multi-camera mode: {len(camera_configs)} USB cameras configured from --devices at {width}x{height}")

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

    # Parse resolution for USB cameras
    resolution = parse_resolution(args.resolution)

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
        axis_configs=camera_configs,
        camera_configs=parsed_camera_configs,
        resolution=resolution,
    )

    scanner.mainloop()
    scanner.close()


if __name__ == "__main__":
    main()
