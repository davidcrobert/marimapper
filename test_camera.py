"""
Quick test to see if a camera is available on device 0.
"""

import cv2
import sys

print("Testing camera access on device 0...")

for capture_method in [cv2.CAP_DSHOW, cv2.CAP_V4L2, cv2.CAP_ANY]:
    print(f"\nTrying capture method: {capture_method}")
    cap = cv2.VideoCapture(0, capture_method)

    if cap.isOpened():
        print(f"  ✓ Camera opened successfully with method {capture_method}")

        # Try to read a frame
        ret, frame = cap.read()
        if ret:
            print(f"  ✓ Frame read successfully: shape={frame.shape}")
        else:
            print(f"  ✗ Failed to read frame")

        cap.release()
        print("\n✓ Camera device 0 is AVAILABLE")
        sys.exit(0)
    else:
        print(f"  ✗ Failed to open camera")

print("\n✗ Camera device 0 is NOT AVAILABLE")
print("Tips:")
print("  - Make sure a webcam is connected")
print("  - Try a different device number: --device 1 or --device 2")
print("  - Check if another application is using the camera")
sys.exit(1)
