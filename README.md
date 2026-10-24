# Cerberus

Named after the three-headed guardian of the underworld, this smart door system has three "heads": sensing, thinking, and acting.

- An **ESP32** watches the doorway with an ultrasonic sensor. When someone steps close, it asks a **Raspberry Pi** to identify them.
- The **Raspberry Pi** captures a frame from its camera, runs a facial-recognition model, and replies **recognized** or **not recognized**.
- The **ESP32** uses that answer to open a servo-driven door lock for known faces only, and keeps it shut otherwise.

```
            ultrasonic              WiFi / HTTP POST /scan              camera + LBPH model
Visitor ───────────────▶  ESP32  ─────────────────────────▶  Raspberry Pi  ───────────────▶ recognized?
                            │                                      │
                            │◀───────── JSON {status, name} ───────┘
                            ▼
                     servo opens door
                     (only if recognized)
```

## Project layout

```
Cerberus/
  face-collector/      Web app (runs on the Pi) used to photograph people and build the dataset
  model-training/      Script that trains the face-recognition model from that dataset
  raspberry-pi/        Server that waits for the ESP32's trigger, runs recognition, replies
  esp32/                Arduino sketch: ultrasonic sensing + servo door control
```

Everything that touches the camera and the trained model lives on the Raspberry Pi; everything that touches the physical door and the ultrasonic sensor lives on the ESP32. They only ever talk to each other over a plain HTTP request over WiFi - by default the Pi's own access point (see [Network setup](#network-setup-pi-as-wifi-access-point)), so no router or phone hotspot is needed.

## 1. `face-collector/` - build your dataset

A small Flask dashboard (meant to run **on the Raspberry Pi**, since it needs the camera) that shows a live preview and saves a photo every time you click **Save image**. Photos are written to `face-collector/dataset/<person-name>/`, one folder per person - the layout the trainer expects.

```bash
cd face-collector
pip install -r requirements.txt          # or: sudo apt install python3-picamera2 python3-opencv python3-flask
python3 app.py
```

Open `http://<pi-ip>:5000` from any device on the same network, type the person's name, and click **Save image** (or press Space) 50-100 times per person while varying angle, distance, and lighting. More people = the model can better tell "known" from "unknown". See [face-collector/README.md](face-collector/README.md) for full details.

This repo already ships a small example dataset (one person, `Adithya`) so you can try the rest of the pipeline immediately - replace/extend it with your own people before relying on it for a real door.

## 2. `model-training/` - train the recognizer

Reads every photo in `face-collector/dataset/`, detects the face in each with an OpenCV Haar-cascade detector, and trains an **LBPH (Local Binary Patterns Histograms)** face recognizer - lightweight enough to run comfortably on a Raspberry Pi, no GPU or heavy `dlib` build required.

```bash
cd model-training
pip install -r requirements.txt
python3 train_model.py
```

This writes `trainer.yml` + `labels.json` and **automatically copies them into `raspberry-pi/model/`**, so the Raspberry Pi server is ready to run immediately after training. Re-run this script any time you add more people or more photos to the dataset.

How recognition decides "known" vs "unknown": LBPH's `predict()` returns a *confidence* value that is really a distance - lower means a closer match. `raspberry-pi/recognize_server.py` treats anything above `CONFIDENCE_THRESHOLD` (default `70`) as **not recognized**, even if the dataset only contains one person. Watch the console output while testing and adjust that constant up/down if real visitors are wrongly accepted or rejected.

## 3. `raspberry-pi/` - the recognition server

Run this **on the Raspberry Pi**, alongside (or instead of) `face-collector`, once you have a trained model in `raspberry-pi/model/`.

```bash
cd raspberry-pi
pip install -r requirements.txt     # or the apt packages from face-collector's README for picamera2
python3 recognize_server.py
```

It starts a small Flask server on port `5001` and:

- Keeps the camera running in the background (uses the Pi ribbon camera module via `picamera2`).
- Exposes `POST /scan` - call it (this is what the ESP32 does) to grab the current frame, detect a face, and run it through the trained model.
- Responds with JSON, e.g.:
  ```json
  {"status": "recognized", "name": "Adithya", "confidence": 42.3}
  {"status": "not_recognized", "reason": "no_face"}
  ```
- Exposes `GET /health` to check it's alive and see which names it knows - handy for testing with `curl http://<pi-ip>:5001/health`.

You can trigger a scan manually to test end-to-end before wiring up the ESP32:

```bash
curl -X POST http://<pi-ip>:5001/scan
```

## 4. `esp32/` - sensing and the door

An Arduino sketch (`esp32/cerberus_esp32/cerberus_esp32.ino`) for any ESP32 dev board. It:

1. Continuously measures distance with an **HC-SR04 ultrasonic sensor**.
2. When something stays closer than `DETECT_DISTANCE_CM` for a few consecutive readings (debounced, so it ignores noise), it sends `POST /scan` to the Raspberry Pi over WiFi.
3. Reads the JSON reply and opens a **servo-driven door latch** for `DOOR_OPEN_MS` milliseconds if `status == "recognized"`, or flashes a red LED / buzzes briefly if not.
4. Auto-closes the door after the timeout and enforces a cooldown between scans so it doesn't spam the Pi.

### Wiring

| Component          | ESP32 pin (default, see `config.h`) | Notes |
|---------------------|----------------------------------|-------|
| HC-SR04 `TRIG`      | GPIO 5                           | 3.3V logic, fine to drive directly |
| HC-SR04 `ECHO`      | GPIO 18                          | **HC-SR04 echo is 5V** - use a voltage divider (e.g. 1k + 2k resistors) or a level shifter before this pin |
| Servo signal        | GPIO 13                          | Power the servo from 5V/USB, **not** the ESP32's 3.3V rail; share ground |
| Green LED (granted) | GPIO 25                          | Through a ~220Ω resistor |
| Red LED (denied)    | GPIO 26                          | Through a ~220Ω resistor |
| Buzzer (optional)   | GPIO 27                          | Active or passive piezo buzzer |

### Build & flash

1. In Arduino IDE, install the **ESP32 board package** and these libraries (Library Manager): `ESP32Servo`, `ArduinoJson`.
2. Copy `esp32/cerberus_esp32/config.example.h` to `esp32/cerberus_esp32/config.h` and the defaults already match the Pi access point described in [Network setup](#network-setup-pi-as-wifi-access-point) (`CerberusNet`, Pi at `192.168.4.1`), so you normally change nothing. `config.h` is gitignored so any WiFi password you set there never gets committed.
3. Open `esp32/cerberus_esp32/cerberus_esp32.ino`, select your board/port, and upload.
4. Open the Serial Monitor at 115200 baud to watch it connect to WiFi, detect visitors, and log the Pi's responses.

## Network setup (Pi as WiFi access point)

The Pi creates its own WiFi network and the ESP32 joins it. The Pi's address is then always `192.168.4.1`, no matter which phone or router is nearby, so nothing needs reconfiguring when you move the project. No internet is required.

```bash
sudo nmcli con add type wifi ifname wlan0 con-name CerberusAP autoconnect yes \
  ssid CerberusNet mode ap ipv4.method shared ipv4.addresses 192.168.4.1/24 \
  wifi-sec.key-mgmt wpa-psk wifi-sec.psk "12345678"
sudo nmcli con up CerberusAP
```

- WPA2 needs a password of **8-63 characters**, so the demo password is `12345678`. Change it (and `WIFI_PASSWORD` in `config.h`) before any real use.
- `wlan0` becomes the access point, so the Pi no longer joins other WiFi on it. Reach the Pi by Ethernet, or by joining `CerberusNet` from your laptop (`ssh pi@192.168.4.1`, `http://192.168.4.1:5001/snapshot`).
- Optional internet for the Pi: USB tethering from a phone uses the separate `usb0` interface and works alongside the access point.
- The ESP32 only supports 2.4 GHz WiFi, which is what the access point uses by default.

## End-to-end setup order

1. Collect photos with `face-collector` (on the Pi) for everyone who should be let in.
2. Train the model with `model-training/train_model.py` - it feeds `raspberry-pi/model/` automatically.
3. Start `raspberry-pi/recognize_server.py` on the Pi and sanity-check it with `curl -X POST http://192.168.4.1:5001/scan`.
4. Flash the ESP32 with your WiFi/Pi settings in `config.h`, wire up the sensor/servo/LEDs, and power it on.
5. Walk up to the sensor - the door should open for known faces and stay shut (with a red-LED/buzzer denial) for anyone else.

## Security & privacy notes

- `face-collector` and `recognize_server.py` have no authentication and listen on all network interfaces - only run them on a trusted local network, never exposed to the internet.
- Face photos are personal data. Keep `face-collector/dataset/` and the trained `trainer.yml`/`labels.json` private, and get consent from anyone you add to the dataset.
- LBPH with a single enrolled person has no true "negative" examples to learn from - it relies entirely on the confidence threshold to reject strangers. For higher security, enroll several people and test the threshold against photos of people who are *not* in the dataset before trusting it to guard a real door.
