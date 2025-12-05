import os
from marimapper.led import Point2D, Point3D, LED3D, LED2D
import typing
from pathlib import Path
import numpy as np


def load_detections(filename: Path, view_id) -> typing.Optional[list[LED2D]]:

    if not os.path.exists(filename):
        return None

    if not filename.suffix == ".csv":
        return None

    with open(filename, "r") as f:
        lines = f.readlines()

    headings = lines[0].strip().split(",")

    if headings != ["index", "u", "v"]:
        return None

    leds = []

    for i in range(1, len(lines)):

        line = lines[i].strip().split(",")

        try:
            index = int(line[0])
            u = float(line[1])
            v = float(line[2])
        except (IndexError, ValueError):
            continue

        leds.append(LED2D(index, view_id, Point2D(u, v)))

    return leds


def get_all_2d_led_maps(directory: Path) -> list[LED2D]:
    points = []

    for view_id, filename in enumerate(sorted(os.listdir(directory))):
        full_path = Path(directory, filename)

        detections = load_detections(
            full_path, view_id
        )  # this is wrong < WHY DID I WRITE THIS???? IS IT NOT???

        if detections is not None:
            points.extend(detections)

    return points


def write_2d_leds_to_file(leds: list[LED2D], filename: Path):

    lines = ["index,u,v"]

    for led in sorted(leds, key=lambda led_t: led_t.led_id):
        lines.append(f"{led.led_id}," f"{led.point.u():f}," f"{led.point.v():f}")

    with open(filename, "w") as f:
        f.write("\n".join(lines))


def load_3d_leds_from_file(filename: Path) -> typing.Optional[list[LED3D]]:
    """Load 3D LED data from CSV file.

    Args:
        filename: Path to led_map_3d.csv file

    Returns:
        List of LED3D objects, or None if file doesn't exist or is invalid
    """
    if not os.path.exists(filename):
        return None

    if not filename.suffix == ".csv":
        return None

    try:
        with open(filename, "r") as f:
            lines = f.readlines()

        if len(lines) < 2:  # Need at least header and one data line
            return None

        headings = lines[0].strip().split(",")

        if headings != ["index", "x", "y", "z", "xn", "yn", "zn", "error"]:
            return None

        leds = []

        for i in range(1, len(lines)):
            line = lines[i].strip().split(",")

            try:
                led_id = int(line[0])
                x = float(line[1])
                y = float(line[2])
                z = float(line[3])
                xn = float(line[4])
                yn = float(line[5])
                zn = float(line[6])
                error = float(line[7])
            except (IndexError, ValueError):
                continue

            # Create LED3D object
            led = LED3D(led_id)
            led.point.position = np.array([x, y, z])
            led.point.normal = np.array([xn, yn, zn])
            led.point.error = error

            leds.append(led)

        return leds if len(leds) > 0 else None

    except Exception:
        return None


def write_3d_leds_to_file(leds: list[LED3D], filename: Path):

    lines = ["index,x,y,z,xn,yn,zn,error"]

    for led in sorted(leds, key=lambda led_t: led_t.led_id):
        lines.append(
            f"{led.led_id},"
            f"{led.point.position[0]:f},"
            f"{led.point.position[1]:f},"
            f"{led.point.position[2]:f},"
            f"{led.point.normal[0]:f},"
            f"{led.point.normal[1]:f},"
            f"{led.point.normal[2]:f},"
            f"{led.point.error:f}"
        )

    with open(filename, "w") as f:
        f.write("\n".join(lines))
