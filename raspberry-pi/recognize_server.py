"""
Cerberus - Raspberry Pi facial recognition module.

Waits for a "scan" trigger from the ESP32 (sent over WiFi when its
ultrasonic sensor detects someone nearby), captures a frame from the
camera, runs the LBPH face-recognition model trained by
model-training/train_model.py, and replies with the result so the ESP32
can decide whether to open the door.

Run:  python3 recognize_server.py
The ESP32 calls:  POST http://<pi-ip>:5001/scan
"""
import json
import os
import threading
import time

import cv2
from flask import Flask, jsonify

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(HERE, "model")
TRAINER_PATH = os.path.join(MODEL_DIR, "trainer.yml")
LABELS_PATH = os.path.join(MODEL_DIR, "labels.json")

FACE_SIZE = (200, 200)
# LBPH confidence is a *distance* - lower means a closer match. Faces with a
# confidence above this are treated as "not recognized" (unknown face).
# Tune this using the console output of a few real scans.
CONFIDENCE_THRESHOLD = 70

CASCADE_PATH = os.path.join(HERE, "haarcascade_frontalface_default.xml")
if not os.path.isfile(CASCADE_PATH):
    CASCADE_PATH = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")

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
                main={"size": (1280, 720), "format": "RGB888"})
            self.picam.configure(cfg)
            self.picam.start()
            self.backend = "picamera2"
        except Exception as e:  # fall back to USB webcam
            print(f"[camera] picamera2 unavailable ({e}); trying OpenCV/USB webcam")
            self.cap = cv2.VideoCapture(0)
            if not self.cap.isOpened():
                raise RuntimeError("No camera found")
            self.backend = "opencv"
        print(f"[camera] using {self.backend}")
        threading.Thread(target=self._loop, daemon=True).start()
        time.sleep(1)  # let the first frame arrive before anyone calls get()

    def _loop(self):
        while True:
            if self.picam is not None:
                frame = self.picam.capture_array()
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


def load_model():
    if not os.path.isfile(TRAINER_PATH) or not os.path.isfile(LABELS_PATH):
        raise SystemExit(
            f"No trained model found in {MODEL_DIR}.\n"
            "Run model-training/train_model.py first (it copies the model here)."
        )
    recognizer = cv2.face.LBPHFaceRecognizer_create()
    recognizer.read(TRAINER_PATH)
    with open(LABELS_PATH) as f:
        label_names = json.load(f)["labels"]
    print(f"[model] loaded {len(label_names)} known face(s): {label_names}")
    return recognizer, label_names


def detect_face(gray_img, cascade):
    faces = cascade.detectMultiScale(
        gray_img, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60)
    )
    if len(faces) == 0:
        return None
    x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
    crop = gray_img[y : y + h, x : x + w]
    return cv2.resize(crop, FACE_SIZE)


camera = Camera()
recognizer, label_names = load_model()
face_cascade = cv2.CascadeClassifier(CASCADE_PATH)
if face_cascade.empty():
    raise SystemExit(f"Could not load Haar cascade from {CASCADE_PATH}")


@app.route("/scan", methods=["POST", "GET"])
def scan():
    """Called by the ESP32 when its ultrasonic sensor detects someone."""
    frame = camera.get()
    if frame is None:
        return jsonify(status="error", message="camera not ready"), 503

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    face = detect_face(gray, face_cascade)

    if face is None:
        print("[scan] no face found in frame")
        return jsonify(status="not_recognized", reason="no_face")

    label_id, confidence = recognizer.predict(face)
    name = label_names[label_id] if label_id < len(label_names) else "unknown"
    recognized = confidence <= CONFIDENCE_THRESHOLD

    print(f"[scan] best match={name} confidence={confidence:.1f} "
          f"-> {'RECOGNIZED' if recognized else 'NOT RECOGNIZED'}")

    if recognized:
        return jsonify(status="recognized", name=name, confidence=round(confidence, 1))
    return jsonify(status="not_recognized", name=name, confidence=round(confidence, 1))


@app.route("/health")
def health():
    return jsonify(status="ok", known_faces=label_names)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, threaded=True)
