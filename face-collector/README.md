# Face Collector (Raspberry Pi)

Web dashboard that shows the live camera feed and saves a photo each time you click **Save image** (or press Space). Photos go into `dataset/<person-name>/`, which is the folder layout most face-recognition training code expects.

## Setup on the Pi

```bash
sudo apt update
sudo apt install -y python3-picamera2 python3-opencv python3-flask   # Pi camera module (CSI)
cd face-collector
python3 app.py
```

If you create a virtualenv for the Pi camera, use `python3 -m venv --system-site-packages venv` so `picamera2` is visible.

## Use

1. Open `http://<pi-ip>:5000` from any device on the same network (`hostname -I` shows the Pi's IP).
2. Type the person's name in the box (it becomes the folder name).
3. Click **Save image** or press **Space**. Vary angles, lighting, and expressions; 50-100 images per person is a good start.

## Layout

```
face-collector/
  app.py
  templates/index.html
  dataset/
    me/20261016_153400_123456.jpg
    friend/...
```

## Settings (top of app.py)

- `FRAME_SIZE` - capture/saved resolution (default 1280x720)
- `STREAM_FPS`, `STREAM_QUALITY` - preview smoothness vs. bandwidth
- `SAVE_QUALITY` - JPEG quality of saved images

## Notes

- The app has no login and listens on all interfaces, so only run it on a trusted network. Face images are personal data; keep the `dataset/` folder private.
- Run on boot (optional): create a systemd service that runs `python3 /home/pi/face-collector/app.py`.
