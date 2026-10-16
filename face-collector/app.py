"""
Face dataset collector - Raspberry Pi camera dashboard.

Run:  python3 app.py
Open: http://<pi-ip>:5000
"""
import os
import re
import threading
import time
from datetime import datetime

import cv2
from flask import Flask, Response, jsonify, render_template, request, send_from_directory

DATASET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dataset")
FRAME_SIZE = (1280, 720)      # capture resolution (saved images use this)
STREAM_FPS = 15               # preview frame rate sent to browser
STREAM_QUALITY = 70           # JPEG quality of preview
SAVE_QUALITY = 95             # JPEG quality of saved images

os.makedirs(DATASET_DIR, exist_ok=True)
app = Flask(__name__)


class Camera:
    """Grabs frames in a background thread; keeps only the latest one."""

    def __init__(self):
        self.lock = threading.Lock()
        self.frame = None
        self.picam = None
        self.cap = None
        try:
            from picamera2 import Picamera2  # Pi camera module (CSI)
            self.picam = Picamera2()
            cfg = self.picam.create_video_configuration(
                main={"size": FRAME_SIZE, "format": "RGB888"})
            self.picam.configure(cfg)
            self.picam.start()
            self.backend = "picamera2"
        except Exception as e:  # fall back to USB webcam
            print(f"[camera] picamera2 unavailable ({e}); trying OpenCV/USB webcam")
            self.cap = cv2.VideoCapture(0)
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_SIZE[0])
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_SIZE[1])
            if not self.cap.isOpened():
                raise RuntimeError("No camera found")
            self.backend = "opencv"
        print(f"[camera] using {self.backend}")
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while True:
            if self.picam is not None:
                frame = self.picam.capture_array()  # RGB888 => BGR byte order, OpenCV-ready
            else:
                ok, frame = self.cap.read()
                if not ok:
                    time.sleep(0.1)
                    continue
            with self.lock:
                self.frame = frame

    def get(self):
        with self.lock:
            return None if self.frame is None else self.frame.copy()


camera = Camera()


def safe_label(name: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_-]+", "_", (name or "").strip())
    return name or "unlabeled"


def mjpeg():
    delay = 1.0 / STREAM_FPS
    while True:
        frame = camera.get()
        if frame is not None:
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, STREAM_QUALITY])
            if ok:
                yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n")
        time.sleep(delay)


def counts():
    result = {}
    for label in sorted(os.listdir(DATASET_DIR)):
        p = os.path.join(DATASET_DIR, label)
        if os.path.isdir(p):
            result[label] = len([f for f in os.listdir(p) if f.lower().endswith(".jpg")])
    return result


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/video_feed")
def video_feed():
    return Response(mjpeg(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/save", methods=["POST"])
def save():
    label = safe_label((request.get_json(silent=True) or {}).get("label"))
    frame = camera.get()
    if frame is None:
        return jsonify(ok=False, error="No frame available yet"), 503
    folder = os.path.join(DATASET_DIR, label)
    os.makedirs(folder, exist_ok=True)
    filename = datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".jpg"
    cv2.imwrite(os.path.join(folder, filename), frame, [cv2.IMWRITE_JPEG_QUALITY, SAVE_QUALITY])
    return jsonify(ok=True, label=label, file=filename, counts=counts())


@app.route("/stats")
def stats():
    c = counts()
    recent = []
    for label in c:
        for f in os.listdir(os.path.join(DATASET_DIR, label)):
            if f.lower().endswith(".jpg"):
                recent.append((f, label))
    recent.sort(reverse=True)
    return jsonify(counts=c, recent=[{"label": l, "file": f} for f, l in recent[:8]])


@app.route("/dataset/<label>/<path:filename>")
def dataset_file(label, filename):
    return send_from_directory(os.path.join(DATASET_DIR, label), filename)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True)
