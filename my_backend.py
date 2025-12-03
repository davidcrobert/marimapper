from pythonosc import udp_client

class Backend:
    def __init__(self, ip: str = "127.0.0.1", port: int = 8000):
        """
        Backend that controls LEDs via OSC.
        :param ip: Target IP address for OSC messages
        :param port: Target port for OSC messages
        """
        self.client = udp_client.SimpleUDPClient(ip, port)

    def get_led_count(self) -> int:
        """Return the number of LEDs available to control."""
        return 216

    def set_led(self, led_index: int, on: bool) -> None:
        """
        Send an OSC message with the LED index and state.
        :param led_index: The index of the LED to control
        :param on: Whether the LED should be on (True) or off (False)
        """
        state = 1 if on else 0
        self.client.send_message("/led", [led_index, state])



        # uv tool install marimapper --with python-osc