import cv2
from datetime import datetime
import requests
from requests.auth import HTTPDigestAuth

CAMERA_HOST = "192.170.100.232"
USERNAME = "root"
PASSWORD = "hemmer"
BASE_URL = f"http://{CAMERA_HOST}/axis-cgi/param.cgi"
PTZ_URL = f"http://{CAMERA_HOST}/axis-cgi/com/ptz.cgi"
CONFIG_FILE = "axis_config_saved.txt"
WHITELIST_PARAMS = {
    "ImageSource.I0.Sensor.ColorLevel",
    "ImageSource.I0.Sensor.Brightness",
    "ImageSource.I0.Sensor.CaptureMode",
    "ImageSource.I0.Sensor.Contrast",
    "ImageSource.I0.Sensor.Sharpness",
    "ImageSource.I0.Sensor.WDR",
    "ImageSource.I0.Sensor.LocalContrast",
    "ImageSource.I0.Sensor.ToneMapping",
    "ImageSource.I0.Sensor.WhiteBalance",
    "ImageSource.I0.Sensor.LowLatencyMode",
}


def _requests_with_fallback(params):
    """Try basic auth first, then digest auth."""
    try:
        resp = requests.get(
            BASE_URL,
            params=params,
            auth=(USERNAME, PASSWORD),
            timeout=5,
        )
        if resp.status_code == 401:
            resp = requests.get(
                BASE_URL,
                params=params,
                auth=HTTPDigestAuth(USERNAME, PASSWORD),
                timeout=5,
            )
        resp.raise_for_status()
        return resp
    except requests.RequestException as exc:
        print(f"[VAPIX] Request failed: {exc}")
        return None


def _ptz_request(params):
    """PTZ endpoint request with basic→digest fallback."""
    merged = {"camera": 1, "html": "no"}
    merged.update(params)
    try:
        resp = requests.get(
            PTZ_URL,
            params=merged,
            auth=(USERNAME, PASSWORD),
            timeout=5,
        )
        if resp.status_code == 401:
            resp = requests.get(
                PTZ_URL,
                params=merged,
                auth=HTTPDigestAuth(USERNAME, PASSWORD),
                timeout=5,
            )
        resp.raise_for_status()
        return resp
    except requests.RequestException as exc:
        print(f"[PTZ] Request failed: {exc}")
        return None


def list_aperture_settings():
    """Fetch and print ALL VAPIX parameters, with iris/aperture highlights."""
    params = {"action": "list"}
    resp = _requests_with_fallback(params)
    if resp is None:
        print("[VAPIX] Failed to read full parameter listing.")
        return

    matches = []
    lines = resp.text.splitlines()
    for line in lines:
        lowered = line.lower()
        if "iris" in lowered or "aperture" in lowered:
            matches.append(line)

    if matches:
        print("[VAPIX] Iris/aperture-related parameters:")
        for line in matches:
            print(f"  {line}")
    else:
        print("[VAPIX] No iris/aperture parameters reported by the camera.")

    print("[VAPIX] Full parameter listing:")
    for line in lines:
        print(f"  {line}")


def get_dc_iris_position():
    """Return current DC iris position (int 0-100) or None if unavailable."""
    resp = _requests_with_fallback({"action": "list", "group": "ImageSource.I0.DCIris"})
    if resp is None:
        return None
    for line in resp.text.splitlines():
        if line.startswith("root.ImageSource.I0.DCIris.Position="):
            try:
                return int(line.split("=", 1)[1].strip())
            except ValueError:
                return None
    return None


def set_dc_iris_enabled(enabled: bool):
    value = "yes" if enabled else "no"
    resp = _requests_with_fallback(
        {"action": "update", "ImageSource.I0.DCIris.Enabled": value}
    )
    if resp is not None:
        print(f"[VAPIX] DCIris.Enabled set to {value}")


def nudge_dc_iris(delta: int):
    """Adjust DC iris position by delta, clamped 0-100, and lock it (DCIris.Enabled=no)."""
    current = get_dc_iris_position()
    if current is None:
        print("[VAPIX] Could not read current iris position.")
        return
    new_pos = max(0, min(100, current + delta))
    resp = _requests_with_fallback(
        {
            "action": "update",
            # On many models, Enabled=no means locked/manual (UI: "Lock aperture")
            "ImageSource.I0.DCIris.Enabled": "no",
            "ImageSource.I0.DCIris.Position": str(new_pos),
        }
    )
    if resp is not None:
        print(f"[VAPIX] DCIris.Position {current} -> {new_pos} (locked/manual)")


def save_camera_config(path: str = CONFIG_FILE):
    """Save whitelisted params + zoom to a file."""
    resp = _requests_with_fallback({"action": "list"})
    if resp is None:
        print("[VAPIX] Could not retrieve parameters to save.")
        return

    params_dict = {}
    for line in resp.text.splitlines():
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip()
        if key.startswith("root."):
            key = key[5:]
        if key in WHITELIST_PARAMS:
            params_dict[key] = val

    zoom_val = None
    zoom_resp = _ptz_request({"query": "position"})
    if zoom_resp is not None:
        for part in zoom_resp.text.strip().split():
            if part.startswith("zoom="):
                try:
                    zoom_raw = part.split("=", 1)[1]
                    # Axis PTZ expects integer zoom (0-9999); coerce floats if returned
                    zoom_val = str(int(round(float(zoom_raw))))
                except (IndexError, ValueError):
                    zoom_val = None
    if zoom_val is None:
        # Fallback to a safe default if zoom query fails
        zoom_val = "1.0"

    try:
        with open(path, "w", encoding="utf-8") as f:
            if zoom_val is not None:
                f.write(f"ptz.zoom={zoom_val}\n")
            for key in sorted(params_dict.keys()):
                f.write(f"{key}={params_dict[key]}\n")
        print(f"[VAPIX] Saved whitelisted params to {path}")
    except OSError as exc:
        print(f"[VAPIX] Failed to write {path}: {exc}")


def apply_camera_config(config_path: str = CONFIG_FILE):
    """Apply whitelisted params + zoom from config."""
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config_lines = f.read().splitlines()
    except OSError as exc:
        print(f"[VAPIX] Failed to read config {config_path}: {exc}")
        return

    applied = 0
    failed = 0
    zoom_val = None
    for line in config_lines:
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip()
        if not key:
            continue
        if key.startswith("root."):
            key = key[5:]
        if key in ("ptz.zoom", "zoom"):
            # Coerce any numeric string to an int string for VAPIX zoom
            try:
                zoom_val = str(int(round(float(val))))
            except ValueError:
                zoom_val = val
            continue  # handled later
        if key not in WHITELIST_PARAMS:
            continue
        resp = _requests_with_fallback({"action": "update", key: val})
        if resp is None:
            failed += 1
        else:
            applied += 1

    # Apply zoom if present in config
    if zoom_val is not None:
        zoom_resp = _ptz_request({"zoom": zoom_val})
        if zoom_resp is None:
            failed += 1
        else:
            applied += 1

    print(
        f"[VAPIX] Applied {applied} params, failed {failed} from {config_path}"
    )

def main():
    # Axis MJPEG endpoint; credentials in URL for basic auth
    stream_url = f"http://{USERNAME}:{PASSWORD}@{CAMERA_HOST}/axis-cgi/mjpg/video.cgi"

    cap = cv2.VideoCapture(stream_url)
    if not cap.isOpened():
        raise SystemExit(f"Failed to open stream: {stream_url}")

    window = "AXIS Camera Feed (press q to quit)"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    print(
        "Controls: q=quit, p=list params, i=lock aperture (Enabled=no), o=unlock (Enabled=yes), ]=open iris (+5, locked), [=close iris (-5, locked), s=save config (whitelist+zoom), l=load/apply config (includes zoom)"
    )

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                print("Frame grab failed; retrying...")
                continue

            cv2.imshow(window, frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q") or cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
                break
            if key == ord("p"):
                list_aperture_settings()
            if key == ord("i"):
                set_dc_iris_enabled(False)
            if key == ord("o"):
                set_dc_iris_enabled(True)
            if key == ord("]"):
                nudge_dc_iris(+5)
            if key == ord("["):
                nudge_dc_iris(-5)
            if key == ord("s"):
                save_camera_config()
            if key == ord("l"):
                apply_camera_config()
    finally:
        cap.release()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
