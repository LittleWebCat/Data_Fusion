#!/usr/bin/env python3
import csv
import sys
import subprocess
import tempfile
from pathlib import Path
from PIL import Image, ImageDraw

if len(sys.argv) < 3:
    print("Usage: python3 scripts/extract_6cam_sample.py /path/to/dataset sample_index")
    sys.exit(1)

run_dir = Path(sys.argv[1]).expanduser().resolve()
sample_idx = int(sys.argv[2])
sync_csv = run_dir / "camera_sync_manifest.csv"

cams = ["CAM_FRONT", "CAM_FRONT_LEFT", "CAM_FRONT_RIGHT", "CAM_BACK", "CAM_BACK_LEFT", "CAM_BACK_RIGHT"]


def make_blank(text):
    img = Image.new("RGB", (640, 480), color=(0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.text((30, 230), text, fill=(255, 255, 255))
    return img


def extract_frame_to_image(video_path, frame_idx, label):
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    vf = f"select=eq(n\\,{frame_idx}),scale=640:480"
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(video_path),
        "-vf", vf, "-frames:v", "1", "-q:v", "2", str(tmp_path), "-y",
    ]
    try:
        subprocess.run(cmd, check=True)
        img = Image.open(tmp_path).convert("RGB")
    except Exception as e:
        print(f"Failed {label}, frame={frame_idx}: {e}")
        img = make_blank(f"{label} READ FAIL frame={frame_idx}")
    finally:
        try:
            tmp_path.unlink()
        except Exception:
            pass

    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, 640, 45), fill=(0, 0, 0))
    draw.text((15, 15), f"{label} frame={frame_idx}", fill=(255, 255, 255))
    return img

with open(sync_csv, "r") as f:
    rows = list(csv.DictReader(f))

if sample_idx >= len(rows):
    print(f"sample_index too large. Max = {len(rows)-1}")
    sys.exit(1)

row = rows[sample_idx]
imgs = []
for cam in cams:
    video_path = Path(row[f"{cam}_video_path"])
    frame_idx = int(row[f"{cam}_frame_index_in_video"])
    imgs.append(extract_frame_to_image(video_path, frame_idx, cam))

grid = Image.new("RGB", (640 * 3, 480 * 2), color=(0, 0, 0))
positions = [(0, 0), (640, 0), (1280, 0), (0, 480), (640, 480), (1280, 480)]
for img, pos in zip(imgs, positions):
    grid.paste(img, pos)

out_path = run_dir / f"sync_sample_{sample_idx:06d}.jpg"
grid.save(out_path, quality=95)
print(f"Saved: {out_path}")
