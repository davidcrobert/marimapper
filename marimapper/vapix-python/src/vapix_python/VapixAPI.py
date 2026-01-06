import time
import multiprocessing as mp
import requests
from concurrent.futures import ThreadPoolExecutor

from .PTZControl import PTZControl
from .GeolocationAPI import GeolocationAPI

from requests.auth import HTTPDigestAuth

def _vapix_worker_loop(config, request_queue):
    """
    Worker process that owns the requests.Session and performs all HTTP I/O.
    Receives request descriptors on request_queue and responds via one-shot
    Pipe connections included in each message.
    """
    session = requests.Session()
    session.auth = HTTPDigestAuth(config["user"], config["password"])
    base_url = f"http://{config['host']}/axis-cgi"
    timeout = config["timeout"]

    while True:
        message = request_queue.get()
        if message is None:
            break
        msg_type = message.get("type")
        if msg_type == "shutdown":
            break

        conn = message["conn"]
        endpoint = message["endpoint"]
        method = message.get("method", "GET")
        params = message.get("params")
        base_args = message.get("base_args", True)

        url = f"{base_url}/{endpoint}"
        args = params or {}
        if base_args:
            base_args_dict = {
                "camera": "1",
                "html": "no",
                "timestamp": int(time.time()),
            }
            base_args_dict.update(args)
            args = base_args_dict

        try:
            if method == "GET":
                response = session.get(url, params=args, timeout=timeout)
            else:
                response = session.post(url, data=args, timeout=timeout)
            response.raise_for_status()
            conn.send(("ok", response.text))
        except Exception as exc:
            conn.send(("error", repr(exc)))
        finally:
            conn.close()

    session.close()

class VapixAPI:
    """
    A class that provides an interface to interact with Axis cameras using the VAPIX API.

    Attributes:
    -----------
    host : str
        IP address or domain name of the camera.
    user : str
        Username for the camera's API authentication.
    password : str
        Password for the camera's API authentication.
    base_url : str
        Base URL for accessing the VAPIX API endpoints.
    _process : multiprocessing.Process
        Dedicated process that owns the requests.Session and performs HTTP I/O.
    _request_queue : multiprocessing.Queue
        Queue used to send request descriptors to the worker process.
    executor : ThreadPoolExecutor
        Thread pool for non-blocking request submissions.
    ptz : PTZControl
        Instance for controlling Pan-Tilt-Zoom features of the camera.
    geolocation : GeolocationAPI
        Instance for handling camera's geolocation functionalities.
    """

    def __init__(self, host, user, password, timeout=5, max_workers=4):
        """
        Initializes the VapixAPI with host, user, and password credentials.

        Parameters:
        -----------
        host : str
            IP address or domain name of the camera.
        user : str
            Username for the camera's API authentication.
        password : str
            Password for the camera's API authentication.
        timeout : int, optional
            Timeout for HTTP requests (default is 5 seconds).
        max_workers : int, optional
            Maximum number of worker threads for async requests (default is 4).
        """
        self.host = host
        self.user = user
        self.password = password
        self.base_url = 'http://' + self.host + '/axis-cgi'
        self.timeout = timeout
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="vapix")
        ctx = mp.get_context("spawn")
        self._request_queue = ctx.Queue()
        self._process = ctx.Process(
            target=_vapix_worker_loop,
            args=(
                {
                    "host": self.host,
                    "user": self.user,
                    "password": self.password,
                    "timeout": self.timeout,
                },
                self._request_queue,
            ),
            daemon=True,
        )
        self._process.start()
        self.ptz = PTZControl(self)
        self.geolocation = GeolocationAPI(self)

    def _send_request(self, endpoint, method="GET", params=None, base_args=True):
        """
        Send a synchronous request to a specific VAPIX API endpoint with base arguments.

        NOTE: This is blocking. Use _send_request_async() for non-blocking requests.

        Parameters:
        -----------
        endpoint : str
            The endpoint to which the request is sent.
        method : str, optional
            HTTP request method (default is "GET").
        params : dict, optional
            Parameters to be included in the request.
        base_args : bool, optional
            Flag to decide if base arguments need to be included (default is True).

        Returns:
        --------
        str
            Response text from the request.

        Raises:
        -------
        requests.RequestException
            If the request encounters an error.
        """
        parent_conn, child_conn = mp.Pipe(duplex=False)
        self._request_queue.put(
            {
                "type": "request",
                "endpoint": endpoint,
                "method": method,
                "params": params,
                "base_args": base_args,
                "conn": child_conn,
            }
        )
        status, payload = parent_conn.recv()
        parent_conn.close()
        if status == "ok":
            return payload
        raise requests.RequestException(payload)

    def _send_request_async(self, endpoint, method="GET", params=None, base_args=True, callback=None, error_callback=None):
        """
        Send an asynchronous non-blocking request to a VAPIX API endpoint.

        This submits the request to a thread pool and returns immediately.

        Parameters:
        -----------
        endpoint : str
            The endpoint to which the request is sent.
        method : str, optional
            HTTP request method (default is "GET").
        params : dict, optional
            Parameters to be included in the request.
        base_args : bool, optional
            Flag to decide if base arguments need to be included (default is True).
        callback : callable, optional
            Function to call with the response text when request succeeds.
        error_callback : callable, optional
            Function to call with the exception if request fails.

        Returns:
        --------
        concurrent.futures.Future
            Future object representing the asynchronous request.
        """
        def _execute_request():
            try:
                result = self._send_request(endpoint, method, params, base_args)
                if callback:
                    callback(result)
                return result
            except Exception as e:
                if error_callback:
                    error_callback(e)
                else:
                    # Silently log errors for fire-and-forget requests
                    print(f"VAPIX async request error: {e}")
                raise

        return self.executor.submit(_execute_request)
        
    def _send_request_vanilla(self, endpoint, method="GET", params=None):
        """
        Send a synchronous request to a specific VAPIX API endpoint without base arguments.

        NOTE: This is blocking. Use _send_request_vanilla_async() for non-blocking requests.

        Parameters:
        -----------
        endpoint : str
            The endpoint to which the request is sent.
        method : str, optional
            HTTP request method (default is "GET").
        params : dict, optional
            Parameters to be included in the request.

        Returns:
        --------
        str
            Response text from the request.

        Raises:
        -------
        requests.RequestException
            If the request encounters an error.
        """
        parent_conn, child_conn = mp.Pipe(duplex=False)
        self._request_queue.put(
            {
                "type": "request",
                "endpoint": endpoint,
                "method": method,
                "params": params,
                "base_args": False,
                "conn": child_conn,
            }
        )
        status, payload = parent_conn.recv()
        parent_conn.close()
        if status == "ok":
            return payload
        raise requests.RequestException(payload)

    def _send_request_vanilla_async(self, endpoint, method="GET", params=None, callback=None, error_callback=None):
        """
        Send an asynchronous non-blocking request to a VAPIX API endpoint without base arguments.

        Parameters:
        -----------
        endpoint : str
            The endpoint to which the request is sent.
        method : str, optional
            HTTP request method (default is "GET").
        params : dict, optional
            Parameters to be included in the request.
        callback : callable, optional
            Function to call with the response text when request succeeds.
        error_callback : callable, optional
            Function to call with the exception if request fails.

        Returns:
        --------
        concurrent.futures.Future
            Future object representing the asynchronous request.
        """
        def _execute_request():
            try:
                result = self._send_request_vanilla(endpoint, method, params)
                if callback:
                    callback(result)
                return result
            except Exception as e:
                if error_callback:
                    error_callback(e)
                else:
                    print(f"VAPIX async request error: {e}")
                raise

        return self.executor.submit(_execute_request)

    def close(self):
        """Close the session and shutdown the thread pool executor."""
        self.executor.shutdown(wait=False)
        if hasattr(self, "_process") and self._process.is_alive():
            self._request_queue.put({"type": "shutdown"})
            self._process.join(timeout=2)
            if self._process.is_alive():
                self._process.terminate()
        if hasattr(self, "_request_queue"):
            self._request_queue.close()


if __name__ == '__main__':
    import time
    import os
    import dotenv
    dotenv.load_dotenv()
    vapix_api = VapixAPI(os.environ.get('host'), os.environ.get('user'), os.environ.get('password'))

    print(vapix_api.ptz.get_current_position())

    vapix_api.close()
