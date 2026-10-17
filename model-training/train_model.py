"""
Train the face-recognition model from the face-collector dataset.

Reads images from ../face-collector/dataset/<person-name>/*.jpg, detects the
face in each one, and trains an OpenCV LBPH recognizer. The trained model
(trainer.yml + labels.json) is written here AND copied into
../raspberry-pi/model/ so the Raspberry Pi module is ready to run immediately.

Run:  python3 train_model.py
"""
import json
import os
import shutil

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATASET_DIR = os.path.join(HERE, "..", "face-collector", "dataset")
OUTPUT_DIR = HERE
PI_MODEL_DIR = os.path.join(HERE, "..", "raspberry-pi", "model")

FACE_SIZE = (200, 200)  # all cropped faces are resized to this before training

# Bundled locally because some OpenCV wheels (e.g. opencv-contrib-python on
# very new Python versions) ship without cv2.data.haarcascades populated.
CASCADE_PATH = os.path.join(HERE, "haarcascade_frontalface_default.xml")
if not os.path.isfile(CASCADE_PATH):
    CASCADE_PATH = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")

face_cascade = cv2.CascadeClassifier(CASCADE_PATH)
if face_cascade.empty():
    raise SystemExit(f"Could not load Haar cascade from {CASCADE_PATH}")


def detect_face(gray_img):
    """Return the largest detected face crop (grayscale, resized), or None."""
    faces = face_cascade.detectMultiScale(
        gray_img, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60)
    )
    if len(faces) == 0:
        return None
    x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
    crop = gray_img[y : y + h, x : x + w]
    return cv2.resize(crop, FACE_SIZE)


def load_dataset():
    labels = []
    label_names = []
    samples = []

    if not os.path.isdir(DATASET_DIR):
        raise SystemExit(f"Dataset folder not found: {DATASET_DIR}")

    people = sorted(
        d for d in os.listdir(DATASET_DIR) if os.path.isdir(os.path.join(DATASET_DIR, d))
    )
    if not people:
        raise SystemExit(f"No person folders found in {DATASET_DIR}")

    for person in people:
        person_dir = os.path.join(DATASET_DIR, person)
        label_id = len(label_names)
        label_names.append(person)

        image_files = [f for f in os.listdir(person_dir) if f.lower().endswith((".jpg", ".jpeg", ".png"))]
        used = 0
        for fname in image_files:
            path = os.path.join(person_dir, fname)
            img = cv2.imread(path)
            if img is None:
                print(f"  [skip] unreadable image: {path}")
                continue
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            face = detect_face(gray)
            if face is None:
                print(f"  [skip] no face detected: {path}")
                continue
            samples.append(face)
            labels.append(label_id)
            used += 1
        print(f"[{person}] {used}/{len(image_files)} images used")

    return samples, labels, label_names


def main():
    print(f"Loading dataset from {os.path.abspath(DATASET_DIR)} ...")
    samples, labels, label_names = load_dataset()

    if len(samples) == 0:
        raise SystemExit("No usable faces found - check lighting/angles and re-collect images.")

    print(f"\nTraining LBPH recognizer on {len(samples)} face samples "
          f"across {len(label_names)} person(s): {label_names}")

    recognizer = cv2.face.LBPHFaceRecognizer_create()
    recognizer.train(samples, np.array(labels))

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    trainer_path = os.path.join(OUTPUT_DIR, "trainer.yml")
    labels_path = os.path.join(OUTPUT_DIR, "labels.json")

    recognizer.write(trainer_path)
    with open(labels_path, "w") as f:
        json.dump({"labels": label_names}, f, indent=2)

    print(f"\nSaved model:  {trainer_path}")
    print(f"Saved labels: {labels_path}")

    # Make the Raspberry Pi module ready to run immediately.
    os.makedirs(PI_MODEL_DIR, exist_ok=True)
    shutil.copy(trainer_path, os.path.join(PI_MODEL_DIR, "trainer.yml"))
    shutil.copy(labels_path, os.path.join(PI_MODEL_DIR, "labels.json"))
    print(f"Copied model into {os.path.abspath(PI_MODEL_DIR)} (used by raspberry-pi/recognize_server.py)")


if __name__ == "__main__":
    main()
