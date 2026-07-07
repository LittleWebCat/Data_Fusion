#!/usr/bin/env python3
import argparse
import os
import sys
import time
from pathlib import Path
import cv2
import numpy as np

KIT_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = Path(os.environ.get("CONFIG_PATH", KIT_DIR / "config" / "config.env")).expanduser()


def load_config(path: Path):
    cfg = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip().strip('"').strip("'")
        v = os.path.expandvars(os.path.expanduser(v))
        cfg[k.strip()] = v
    return cfg

cfg = load_config(CONFIG_PATH)


def parse_args():
    parser = argparse.ArgumentParser(description="Preview all six cameras in a 3x2 grid.")
    parser.add_argument("--width", type=int, default=int(os.environ.get("PREVIEW_WIDTH", "640")))
    parser.add_argument("--height", type=int, default=int(os.environ.get("PREVIEW_HEIGHT", "480")))
    parser.add_argument("--fps", type=int, default=int(os.environ.get("PREVIEW_FPS", cfg.get("FPS", "15"))))
    return parser.parse_args()


args = parse_args()
WIDTH_PREVIEW = args.width
HEIGHT_PREVIEW = args.height
FPS_PREVIEW = args.fps

cams = [
    ("CAM_FRONT_LEFT", cfg.get("CAM_FRONT_LEFT", "/dev/video2")),
    ("CAM_FRONT", cfg.get("CAM_FRONT", "/dev/video0")),
    ("CAM_FRONT_RIGHT", cfg.get("CAM_FRONT_RIGHT", "/dev/video4")),
    ("CAM_BACK_LEFT", cfg.get("CAM_BACK_LEFT", "/dev/video8")),
    ("CAM_BACK", cfg.get("CAM_BACK", "/dev/video6")),
    ("CAM_BACK_RIGHT", cfg.get("CAM_BACK_RIGHT", "/dev/video10")),
]


def make_blank(text):
    img = np.zeros((HEIGHT_PREVIEW, WIDTH_PREVIEW, 3), dtype=np.uint8)
    cv2.putText(img, text, (30, HEIGHT_PREVIEW // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2)
    return img


def normalize_frame(frame):
    if frame is None:
        return make_blank("NO FRAME")
    frame = np.asarray(frame)
    if frame.dtype == np.int8:
        frame = frame.astype(np.uint8)
    elif frame.dtype != np.uint8:
        frame = cv2.convertScaleAbs(frame)
    if frame.ndim == 2:
        frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
    elif frame.ndim == 3 and frame.shape[2] == 1:
        frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
    elif frame.ndim == 3 and frame.shape[2] == 4:
        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
    frame = cv2.resize(frame, (WIDTH_PREVIEW, HEIGHT_PREVIEW))
    return np.ascontiguousarray(frame, dtype=np.uint8)

caps = []
for name, dev in cams:
    cap = cv2.VideoCapture(dev, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH_PREVIEW)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT_PREVIEW)
    cap.set(cv2.CAP_PROP_FPS, FPS_PREVIEW)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    print(f"{name} {dev}: opened={cap.isOpened()}")
    caps.append((name, dev, cap))

time.sleep(1.0)

try:
    while True:
        frames = []
        for name, dev, cap in caps:
            ret, frame = cap.read()
            if not ret:
                frame = make_blank(f"{name} {dev} NO FRAME")
            else:
                frame = normalize_frame(frame)
                cv2.rectangle(frame, (0, 0), (WIDTH_PREVIEW - 1, 45), (0, 0, 0), -1)
                cv2.putText(frame, f"{name} {dev}", (15, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)
                cv2.rectangle(frame, (5, 5), (WIDTH_PREVIEW - 5, HEIGHT_PREVIEW - 5), (255, 255, 255), 2)
            frames.append(frame)
        top = np.hstack(frames[:3])
        bottom = np.hstack(frames[3:])
        grid = np.vstack((top, bottom))
        grid = np.ascontiguousarray(grid, dtype=np.uint8)
        cv2.imshow("6 Camera Preview - q/ESC to quit", grid)
        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), 27):
            break
finally:
    for _, _, cap in caps:
        cap.release()
    cv2.destroyAllWindows()
