"""
Pure LED detection algorithms.

This module contains stateless functions for detecting LEDs in images.
All functions are pure (no side effects) and easily testable.

Key functions:
- find_led_in_image: Detect brightest LED centroid in an image
- contour_brightness: Calculate total brightness within a contour
- draw_led_detections: Render detection overlay on image
"""

from typing import Optional
import cv2
import numpy as np

from marimapper.led import Point2D


def contour_brightness(image: np.ndarray, contour: np.ndarray) -> int:
    """
    Calculate the sum of all pixel values within a contour.

    Args:
        image: Grayscale or BGR image
        contour: OpenCV contour array

    Returns:
        Sum of all pixel values within the contour
    """
    mask = np.zeros(image.shape, dtype=np.uint8)
    cv2.drawContours(mask, [contour], -1, 255, -1)
    masked_image = cv2.bitwise_and(image, image, mask=mask)
    return cv2.sumElems(masked_image)


def find_led_in_image(
    image: np.ndarray,
    threshold: int = 128,
    mask: Optional[np.ndarray] = None,
    mask_resolution: Optional[tuple] = None,
) -> Optional[Point2D]:
    """
    Find the brightest LED in an image using thresholding and contour detection.

    Algorithm:
    1. Convert image to grayscale if needed
    2. Apply detection mask if provided (ignore painted areas)
    3. Threshold image to isolate bright spots
    4. Find contours and select brightest by total pixel sum
    5. Calculate centroid using image moments
    6. Normalize coordinates to [0, 1] range

    Args:
        image: Input image (grayscale or BGR)
        threshold: Brightness threshold (0-255). Pixels below this are ignored.
        mask: Optional binary mask (255 = detect, 0 = ignore)
        mask_resolution: Original resolution of mask as (height, width)

    Returns:
        Point2D with normalized coordinates (u, v) in [0, 1], or None if no LED found
    """
    # Convert to grayscale if needed
    if len(image.shape) > 2:
        image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # Apply detection mask to ignore painted/masked areas
    if mask is not None:
        img_height, img_width = image.shape
        mask_height, mask_width = (
            mask_resolution if mask_resolution else mask.shape
        )

        # Scale mask to match current image resolution if needed
        if (img_height, img_width) != (mask_height, mask_width):
            scaled_mask = cv2.resize(
                mask, (img_width, img_height), interpolation=cv2.INTER_NEAREST
            )
        else:
            scaled_mask = mask

        # Apply mask: 0 = ignore (painted), 255 = detect
        image = cv2.bitwise_and(image, image, mask=scaled_mask)

    # Threshold to isolate bright spots (LED candidates)
    _, image_thresh = cv2.threshold(image, threshold, 255, cv2.THRESH_TOZERO)

    # Find contours of bright regions
    contours, _ = cv2.findContours(image_thresh, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

    if len(contours) == 0:
        return None

    # Select brightest contour by total pixel sum
    brightest_contour = sorted(
        contours, key=lambda c: contour_brightness(image, c), reverse=True
    )[0]

    # Calculate centroid using image moments
    moments = cv2.moments(brightest_contour)

    # Avoid division by zero
    center_u = moments["m10"] / max(moments["m00"], 0.00001)
    center_v = moments["m01"] / max(moments["m00"], 0.00001)

    # Edge case: sometimes centroid is zero (unclear why, but observed in practice)
    if center_u == 0 or center_v == 0:
        return None

    # Normalize coordinates to [0, 1] range
    # Note: v coordinate is adjusted to account for image aspect ratio
    img_height, img_width = image.shape

    center_u = center_u / img_width
    v_offset = (img_width - img_height) / 2.0
    center_v = (center_v + v_offset) / img_width

    return Point2D(center_u, center_v, contours)


def draw_led_detections(
    image: cv2.Mat,
    led_detection: Optional[Point2D],
    color: tuple = (0, 255, 0),
    marker_size: int = 100
) -> np.ndarray:
    """
    Draw LED detection overlay on image.

    Renders a marker at the detected LED position.

    Args:
        image: Input image (grayscale or BGR)
        led_detection: Detected LED position (or None)
        color: BGR color tuple for the marker (default: green)
        marker_size: Size of the marker in pixels (default: 100)

    Returns:
        BGR image with detection marker drawn (if detection provided)
    """
    # Make a writable BGR image (cv2 drawing ops require writeable contiguous memory)
    if len(image.shape) == 3:
        render_image = np.ascontiguousarray(image.copy())
    else:
        render_image = np.ascontiguousarray(cv2.cvtColor(image, cv2.COLOR_GRAY2BGR))

    if led_detection is None:
        return render_image

    # Convert normalized coordinates back to pixel coordinates
    img_height = render_image.shape[0]
    img_width = render_image.shape[1]

    u_abs = int(led_detection.u() * img_width)

    v_offset = (img_width - img_height) / 2.0
    v_abs = int(led_detection.v() * img_width - v_offset)

    # Draw marker at LED position
    cv2.drawMarker(
        render_image,
        (u_abs, v_abs),
        color,
        markerSize=marker_size,
    )

    return render_image


def draw_error_detection(image: cv2.Mat, led_detection: Optional[Point2D]) -> np.ndarray:
    """
    Draw LED detection overlay in red (for errors like darkness check failures).

    Args:
        image: Input image (grayscale or BGR)
        led_detection: Detected LED position (or None)

    Returns:
        BGR image with RED detection marker drawn (if detection provided)
    """
    return draw_led_detections(image, led_detection, color=(0, 0, 255), marker_size=120)
