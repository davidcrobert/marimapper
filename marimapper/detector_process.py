from multiprocessing import get_logger, Process, Queue, Event
import time
from enum import Enum
from marimapper.detector import (
    show_image,
    set_cam_default,
    Camera,
    TimeoutController,
    set_cam_dark,
    enable_and_find_led,
    find_led,
)
from marimapper.led import get_distance, get_color, LEDInfo
from marimapper.queues import (
    RequestDetectionsQueue,
    Queue2D,
    DetectionControlEnum,
    Queue3DInfo,
)
from functools import partial

logger = get_logger()


class CameraCommand(Enum):
    """Commands for controlling camera and detection parameters."""
    SET_DARK = "set_dark"
    SET_BRIGHT = "set_bright"
    SET_THRESHOLD = "set_threshold"  # (command, threshold_value)
    ALL_OFF = "all_off"
    ALL_ON = "all_on"


def backend_black(backend):
    try:
        # Preferred: dedicated blackout implementation on the backend
        if hasattr(backend, "blackout"):
            return backend.blackout()

        # Fallback: bulk-set if supported
        if hasattr(backend, "set_leds"):
            buffer = [[0, 0, 0] for _ in range(backend.get_led_count())]
            backend.set_leds(buffer)
            return True

        # Last resort: iterate per LED (can be slow on some backends)
        if hasattr(backend, "set_led"):
            for i in range(backend.get_led_count()):
                backend.set_led(i, False)
            return True

    except Exception as e:
        logger.debug(f"Failed to blacken backend: {e}")

    return False


def backend_all_on(backend):
    """Turn every LED/pixel fully on using available backend APIs."""
    try:
        # Preferred bulk interface
        if hasattr(backend, "set_leds"):
            buffer = [[255, 255, 255] for _ in range(backend.get_led_count())]
            backend.set_leds(buffer)
            return True

        # Fallback: per-LED iteration
        if hasattr(backend, "set_led"):
            for i in range(backend.get_led_count()):
                backend.set_led(i, True)
            return True
    except Exception as e:
        logger.debug(f"Failed to turn all LEDs on: {e}")

    return False


def render_led_info(led_info: dict[int, LEDInfo], led_backend):
    buffer = [[0, 0, 0] for _ in range(max(led_info.keys()) + 1)]
    for led_id in led_info:
        info = led_info[led_id]
        buffer[led_id] = [int(v / 10) for v in get_color(info)]

    try:
        led_backend.set_leds(buffer)
        return True
    except AttributeError:
        logger.debug(
            "tried to set a colourful backend buffer that doesn't have a set_leds method :("
        )
        return False


def detect_leds(
    led_id_from: int,
    led_id_to: int,
    cam: Camera,
    led_backend,
    view_id: int,
    timeout_controller: TimeoutController,
    threshold: int,
    display: bool,
    output_queues: list[Queue2D],
    frame_queue=None,
):
    leds = []
    for led_id in range(led_id_from, led_id_to):
        led = enable_and_find_led(
            cam,
            led_backend,
            led_id,
            view_id,
            timeout_controller,
            threshold,
            display,
            frame_queue,
        )

        for queue in output_queues:
            if led is not None:
                queue.put(DetectionControlEnum.DETECT, led)
                leds.append(led)
            else:
                queue.put(DetectionControlEnum.SKIP, led_id)
    return leds


class DetectorProcess(Process):

    def __init__(
        self,
        device: str,
        dark_exposure: int,
        threshold: int,
        backend_factory: partial,
        display: bool = True,
        check_movement=True,
        axis_config: dict = None,
        frame_queue: Queue = None,
    ):
        super().__init__()
        self._request_detections_queue = RequestDetectionsQueue()  # {led_id, view_id}
        self._output_queues: list[Queue2D] = []  # LED3D
        self._led_count: Queue = Queue()
        self._led_count.cancel_join_thread()
        self._input_3d_info_queue = Queue3DInfo()
        self._camera_command_queue: Queue = Queue()  # Camera control commands
        self._camera_command_queue.cancel_join_thread()
        self._exit_event = Event()

        self._device = device
        self._dark_exposure = dark_exposure
        self._threshold = threshold
        self._led_backend_factory = backend_factory
        self._display = display
        self._check_movement = check_movement
        self._axis_config = axis_config
        self._frame_queue = frame_queue

    def get_input_3d_info_queue(self):
        return self._input_3d_info_queue

    def get_camera_command_queue(self):
        return self._camera_command_queue

    def get_request_detections_queue(self) -> RequestDetectionsQueue:
        return self._request_detections_queue

    def add_output_queue(self, queue: Queue2D):
        self._output_queues.append(queue)

    def detect(self, led_id_from: int, led_id_to: int, view_id: int):
        self._request_detections_queue.request(led_id_from, led_id_to, view_id)

    def get_led_count(self):
        return self._led_count.get()

    def stop(self):
        self._exit_event.set()

    def put_in_all_output_queues(self, control: DetectionControlEnum, data):
        for queue in self._output_queues:
            queue.put(control, data)

    def run(self):
        try:
            logger.info("DetectorProcess starting...")

            led_backend = self._led_backend_factory()
            logger.info(f"Backend created: {type(led_backend).__name__}")

            led_count = led_backend.get_led_count()
            logger.info(f"LED count: {led_count}")
            self._led_count.put(led_count)

            logger.info(f"Initializing camera (device={self._device}, axis_config={self._axis_config is not None})...")
            cam = Camera(device_id=self._device, axis_config=self._axis_config)
            logger.info("Camera initialized successfully")

            timeout_controller = TimeoutController()

            # we quickly switch to dark mode here to throw any exceptions about the camera early
            logger.info("Setting camera to dark mode for testing...")
            set_cam_dark(cam, self._dark_exposure)
            set_cam_default(cam)
            logger.info("Camera mode test passed")

            logger.info(f"DetectorProcess initialized. Display: {self._display}, Frame queue: {self._frame_queue is not None}")

        except Exception as e:
            logger.error(f"DetectorProcess failed to initialize: {e}")
            import traceback
            traceback.print_exc()
            # Put an error value in led_count queue so caller doesn't hang
            self._led_count.put(-1)
            return

        frame_send_count = 0
        idle_loop_count = 0
        while not self._exit_event.is_set():

            if not self._request_detections_queue.empty():

                led_id_from, led_id_to, view_id = (
                    self._request_detections_queue.get_id_from_id_to_view()
                )

                success = backend_black(led_backend)
                if not success:
                    logger.debug("failed to blacken backend due to missing attribute")

                # scan start here
                set_cam_dark(cam, self._dark_exposure)

                # Firstly, if there are leds visible, break out
                if find_led(cam, self._threshold, self._display, self._frame_queue) is not None:
                    logger.error(
                        "Detector process can detect an LED when no LEDs should be visible"
                    )
                    for queue in self._output_queues:
                        queue.put(DetectionControlEnum.FAIL, None)
                    set_cam_default(cam)
                    continue

                leds = detect_leds(
                    led_id_from,
                    led_id_to,
                    cam,
                    led_backend,
                    view_id,
                    timeout_controller,
                    self._threshold,
                    self._display,
                    self._output_queues,
                    self._frame_queue,
                )

                if leds is not None and len(leds) > 0:

                    movement = False
                    if self._check_movement:
                        led_first = leds[0]

                        led_current = enable_and_find_led(
                            cam,
                            led_backend,
                            led_first.led_id,
                            view_id,
                            timeout_controller,
                            self._threshold,
                            self._display,
                            self._frame_queue,
                        )
                        if led_current is not None:
                            distance = get_distance(led_current, led_first)
                            if distance > 0.01:  # 1% movement
                                logger.error(
                                    f"Camera movement of {int(distance * 100)}% has been detected"
                                )
                                movement = True
                        else:
                            logger.warning(
                                f"Went back to check led {led_first.led_id} for movement, "
                                f"and led could no longer be found. Cannot perform movement check"
                            )  # this is failing unexpectedly, needs test
                            movement = False

                    for queue in self._output_queues:
                        queue.put(
                            (
                                DetectionControlEnum.DONE
                                if not movement
                                else DetectionControlEnum.DELETE
                            ),
                            view_id,
                        )

                # and lets reset everything back to normal
                set_cam_default(cam)

            if self._request_detections_queue.empty():
                idle_loop_count += 1
                if idle_loop_count == 1:
                    logger.info(f"Entering idle loop. Display={self._display}, frame_queue={self._frame_queue is not None}")

                # Check exit event BEFORE blocking on camera read
                if self._exit_event.is_set():
                    break

                if self._display:
                    image = cam.read()
                    # Send frame to GUI if frame_queue is provided
                    if self._frame_queue is not None:
                        # Use put_nowait to avoid blocking if queue is full (drop frames)
                        try:
                            self._frame_queue.put_nowait(image)
                            frame_send_count += 1
                            if frame_send_count <= 3:  # Log first 3 frames
                                logger.info(f"Sent frame {frame_send_count} to GUI queue. Shape: {image.shape}")
                        except Exception as e:
                            if frame_send_count == 0:  # Only log if we haven't sent any frames yet
                                logger.warning(f"Failed to send frame to GUI queue: {e}")
                            pass  # Queue full, drop frame
                    else:
                        # CLI mode: Show window
                        show_image(image)
                    time.sleep(1 / 60)

                if not self._input_3d_info_queue.empty():
                    led_info: dict[int, LEDInfo] = self._input_3d_info_queue.get()

                    success = render_led_info(led_info, led_backend)
                    if not success:
                        logger.debug(
                            "failed to update colourful backend buffer due to a missing attribute"
                        )

                # Handle camera control commands
                if not self._camera_command_queue.empty():
                    try:
                        cmd_data = self._camera_command_queue.get_nowait()

                        # Handle tuple (command, value) or just command
                        if isinstance(cmd_data, tuple):
                            command, value = cmd_data
                        else:
                            command = cmd_data
                            value = None

                        if command == CameraCommand.SET_DARK:
                            logger.info("GUI requested: Setting camera to DARK mode")
                            set_cam_dark(cam, self._dark_exposure)
                            cam.eat()  # Flush frames
                        elif command == CameraCommand.SET_BRIGHT:
                            logger.info("GUI requested: Setting camera to BRIGHT mode")
                            set_cam_default(cam)
                            cam.eat()  # Flush frames
                        elif command == CameraCommand.SET_THRESHOLD:
                            if value is not None:
                                logger.info(f"GUI requested: Setting threshold to {value}")
                                self._threshold = value
                        elif command == CameraCommand.ALL_OFF:
                            logger.info("GUI requested: Turning all LEDs off")
                            backend_black(led_backend)
                        elif command == CameraCommand.ALL_ON:
                            logger.info("GUI requested: Turning all LEDs on")
                            backend_all_on(led_backend)
                    except Exception as e:
                        logger.warning(f"Failed to process camera command: {e}")

        logger.info("detector closing, resetting camera and backend")
        try:
            set_cam_default(cam)
        except Exception as e:
            logger.warning(f"Failed to reset camera to default: {e}")

        try:
            backend_black(led_backend)
        except Exception as e:
            logger.warning(f"Failed to black out backend: {e}")

        # Release camera resources
        try:
            logger.info("Releasing camera...")
            cam.device.release()
            logger.info("Camera released")
        except Exception as e:
            logger.warning(f"Failed to release camera: {e}")

        time.sleep(0.1)  # Brief pause for cleanup
