import cv2
import requests
from requests.auth import HTTPDigestAuth

CAMERA_HOST = "192.170.100.232"
USERNAME = "root"
PASSWORD = "hemmer"
BASE_URL = f"http://{CAMERA_HOST}/axis-cgi/param.cgi"


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
    # else:
    #     print("[VAPIX] No iris/aperture parameters reported by the camera.")

    # print("[VAPIX] Full parameter listing:")
    # for line in lines:
    #     print(f"  {line}")


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

def main():
    # Axis MJPEG endpoint; credentials in URL for basic auth
    stream_url = f"http://{USERNAME}:{PASSWORD}@{CAMERA_HOST}/axis-cgi/mjpg/video.cgi"

    cap = cv2.VideoCapture(stream_url)
    if not cap.isOpened():
        raise SystemExit(f"Failed to open stream: {stream_url}")

    window = "AXIS Camera Feed (press q to quit)"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    print(
        "Controls: q=quit, p=list iris/aperture params, i=lock aperture (DCIris.Enabled=no), o=unlock aperture (Enabled=yes), ]=open iris (+5, locked), [=close iris (-5, locked)"
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
                set_dc_iris_enabled(True)
            if key == ord("o"):
                set_dc_iris_enabled(False)
            if key == ord("]"):
                nudge_dc_iris(+5)
            if key == ord("["):
                nudge_dc_iris(-5)
    finally:
        cap.release()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
