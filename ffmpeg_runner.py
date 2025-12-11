import subprocess
import sys
import logging
import platform
import threading
import queue
import numpy as np
import cv2  # Used ONLY for display (imshow), not for capture.

# --- Configuration ---
# Set the resolution to match your camera's hardware capabilities.
# Mismatched resolutions are a common cause of FFmpeg errors.
WIDTH = 1280
HEIGHT = 720
FPS = 30
DEVICE_INDEX = "22_Cam2"  # '0' is usually the default webcam. On Mac/Windows this might be the device name string.

# --- Logging Setup ---
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - [%(levelname)s] - %(threadName)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("FFmpegStreamer")

def enqueue_output(out, log_queue):
    """
    Reads lines from a stream (stderr) and adds them to a queue.
    This runs in a separate thread to capture FFmpeg logs without blocking.
    """
    for line in iter(out.readline, b''):
        log_queue.put(line)
    out.close()

def get_ffmpeg_command(os_name, device_id, width, height, fps):
    """
    Constructs the OS-specific FFmpeg command.
    """
    cmd = ['ffmpeg', '-hide_banner', '-loglevel', 'error'] # Reduce noise, keep errors

    if os_name == 'Linux':
        # Linux uses video4linux2
        cmd.extend(['-f', 'v4l2', '-input_format', 'mjpeg']) # mjpeg is often safer for USB cams
        cmd.extend(['-framerate', str(fps)])
        cmd.extend(['-video_size', f'{width}x{height}'])
        cmd.extend(['-i', f'/dev/video{device_id}'])
    
    elif os_name == 'Darwin':
        # macOS uses avfoundation
        # Device ID on Mac usually "0" or "0:0"
        cmd.extend(['-f', 'avfoundation'])
        cmd.extend(['-framerate', str(fps)])
        cmd.extend(['-video_size', f'{width}x{height}'])
        cmd.extend(['-i', device_id])
    
    elif os_name == 'Windows':
        # Windows uses dshow
        # Note: Windows requires the specific device name string, not an index.
        # You might need to run `ffmpeg -list_devices true -f dshow -i dummy` to find it.
        cmd.extend(['-f', 'dshow'])
        cmd.extend(['-framerate', str(fps)])
        cmd.extend(['-video_size', f'{width}x{height}'])
        cmd.extend(['-i', f'video={device_id}'])
    
    else:
        logger.critical(f"Unsupported OS: {os_name}")
        sys.exit(1)

    # Output parameters: Raw video piped to stdout
    cmd.extend(['-f', 'image2pipe'])
    cmd.extend(['-pix_fmt', 'bgr24']) # OpenCV uses BGR
    cmd.extend(['-vcodec', 'rawvideo'])
    cmd.extend(['-']) # Output to pipe

    return cmd

def main():
    os_name = platform.system()
    logger.info(f"Detected OS: {os_name}")

    # Calculate exact bytes per frame: Width * Height * 3 (BGR channels)
    frame_size = WIDTH * HEIGHT * 3
    logger.info(f"Frame Size: {WIDTH}x{HEIGHT} (Buffer: {frame_size} bytes)")

    # Build command
    cmd = get_ffmpeg_command(os_name, DEVICE_INDEX, WIDTH, HEIGHT, FPS)
    logger.info(f"FFmpeg Command: {' '.join(cmd)}")

    process = None
    
    try:
        # Start FFmpeg process
        # stdout=PIPE for video data, stderr=PIPE for logging
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=10**8  # Large buffer to prevent pipe blocking
        )

        # Start a thread to capture stderr (FFmpeg logs/errors)
        log_queue = queue.Queue()
        log_thread = threading.Thread(target=enqueue_output, args=(process.stderr, log_queue))
        log_thread.daemon = True # Ensure thread dies if main program dies
        log_thread.start()

        logger.info("Stream started. Press 'q' to quit.")

        while True:
            # 1. Read the exact number of bytes for one frame
            in_bytes = process.stdout.read(frame_size)

            # 2. Check if we got a complete frame
            if len(in_bytes) == 0:
                logger.warning("Received 0 bytes from FFmpeg stdout. Pipe might be closed.")
                break
            
            if len(in_bytes) != frame_size:
                # If we get partial data, it usually means the pipe broke or EOF
                logger.warning(f"Incomplete frame read: {len(in_bytes)}/{frame_size} bytes. Skipping.")
                continue

            # 3. Convert bytes to NumPy array for OpenCV
            frame = np.frombuffer(in_bytes, np.uint8).reshape((HEIGHT, WIDTH, 3))

            # 4. Display the frame
            cv2.imshow('FFmpeg Capture', frame)

            # 5. Check for 'q' key to quit
            if cv2.waitKey(1) & 0xFF == ord('q'):
                logger.info("Quit requested by user.")
                break
            
            # 6. Check for FFmpeg errors in the queue non-blocking
            try:
                while True:
                    line = log_queue.get_nowait()
                    # Decode bytes to string
                    logger.error(f"FFmpeg stderr: {line.decode('utf-8').strip()}")
            except queue.Empty:
                pass

    except FileNotFoundError:
        logger.critical("FFmpeg executable not found. Please ensure ffmpeg is installed and in your PATH.")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
    finally:
        # Cleanup
        if process:
            logger.info("Terminating FFmpeg process...")
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
        
        cv2.destroyAllWindows()
        logger.info("Exiting.")

if __name__ == '__main__':
    main()