#!/usr/bin/env python3
import csv
import os
import subprocess
from pathlib import Path
import sys

KIT_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = Path(os.environ.get("CONFIG_PATH", KIT_DIR / "config" / "config.env")).expanduser()


def load_config(path: Path):
    cfg = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        cfg[k.strip()] = os.path.expandvars(os.path.expanduser(v.strip().strip('"').strip("'")))
    return cfg

cfg = load_config(CONFIG_PATH)
FPS = int(cfg.get("FPS", 15))
WARMUP_FRAMES = int(cfg.get("WARMUP_FRAMES", 5))
CAMS = ["CAM_FRONT", "CAM_FRONT_LEFT", "CAM_FRONT_RIGHT", "CAM_BACK", "CAM_BACK_LEFT", "CAM_BACK_RIGHT"]


def count_frames(video_path: Path) -> int:
    cmd = [
        "ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
        "-show_entries", "stream=nb_read_frames", "-of", "default=nokey=1:noprint_wrappers=1", str(video_path)
    ]
    out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL).strip()
    return int(out)

if len(sys.argv) != 2:
    print("Usage: python3 scripts/make_6cam_manifest.py /path/to/dataset_folder")
    sys.exit(1)

run_dir = Path(sys.argv[1]).expanduser().resolve()
manifest_path = run_dir / "camera_manifest.csv"
rows = []

for cam in CAMS:
    video_path = run_dir / cam / "video.mkv"
    if not video_path.exists():
        print(f"Missing: {video_path}")
        continue
    n = count_frames(video_path)
    usable = max(0, n - WARMUP_FRAMES)
    print(f"{cam}: total={n}, usable_after_warmup={usable}")
    for frame_idx in range(WARMUP_FRAMES, n):
        usable_idx = frame_idx - WARMUP_FRAMES
        rows.append({
            "camera": cam,
            "video_path": str(video_path),
            "frame_index_in_video": frame_idx,
            "usable_frame_index": usable_idx,
            "nominal_time_s": usable_idx / FPS,
            "fps": FPS,
            "warmup_frames": WARMUP_FRAMES,
        })

with open(manifest_path, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=["camera", "video_path", "frame_index_in_video", "usable_frame_index", "nominal_time_s", "fps", "warmup_frames"])
    writer.writeheader()
    writer.writerows(rows)

print(f"Saved manifest: {manifest_path}")
print(f"Total manifest rows: {len(rows)}")
