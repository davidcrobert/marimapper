"""
Quick diagnostic script to test if frames are flowing through the frame_queue.
"""

import multiprocessing
import time
from multiprocessing import Queue

# CRITICAL: Must set spawn before any imports
multiprocessing.set_start_method("spawn", force=True)

from marimapper.scanner import Scanner
from marimapper.backends.backend_utils import backend_factories
from pathlib import Path
import argparse

def test_frame_queue():
    print("Creating frame queue...")
    frame_queue = Queue(maxsize=3)

    print("Initializing scanner with frame queue...")

    # Create dummy backend
    parser = argparse.ArgumentParser()
    parser.add_argument('--backend', default='dummy')
    args = parser.parse_args(['--backend', 'dummy'])
    backend_factory = backend_factories['dummy'](args)

    try:
        scanner = Scanner(
            output_dir=Path('.'),
            device=0,
            exposure=1,
            threshold=128,
            backend_factory=backend_factory,
            led_start=0,
            led_end=10,
            interpolation_max_fill=10,
            interpolation_max_error=0.5,
            check_movement=False,
            camera_model_name='SIMPLE_PINHOLE',
            axis_config=None,
            frame_queue=frame_queue,
        )

        print(f"Scanner created. LED count: {scanner.detector.get_led_count()}")
        print("Detector process started, waiting for frames...")

        # Wait for frames
        for i in range(10):
            print(f"\nAttempt {i+1}/10:")
            print(f"  - Queue empty: {frame_queue.empty()}")
            print(f"  - Queue size: {frame_queue.qsize()}")
            print(f"  - Detector alive: {scanner.detector.is_alive()}")

            if not frame_queue.empty():
                frame = frame_queue.get_nowait()
                print(f"  - Got frame! Shape: {frame.shape}, dtype: {frame.dtype}")
            else:
                print(f"  - No frames yet...")

            time.sleep(1)

        print("\nTest complete. Closing scanner...")
        scanner.close()

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_frame_queue()
