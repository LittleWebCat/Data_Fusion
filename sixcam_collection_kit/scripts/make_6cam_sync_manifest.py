#!/usr/bin/env python3
import csv
import os
from collections import defaultdict
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
CAMS = ["CAM_FRONT", "CAM_FRONT_LEFT", "CAM_FRONT_RIGHT", "CAM_BACK", "CAM_BACK_LEFT", "CAM_BACK_RIGHT"]

if len(sys.argv) != 2:
    print("Usage: python3 scripts/make_6cam_sync_manifest.py /path/to/dataset_folder")
    sys.exit(1)

run_dir = Path(sys.argv[1]).expanduser().resolve()
manifest_path = run_dir / "camera_manifest.csv"
sync_path = run_dir / "camera_sync_manifest.csv"

rows_by_cam = defaultdict(list)
with open(manifest_path, "r") as f:
    reader = csv.DictReader(f)
    for row in reader:
        rows_by_cam[row["camera"]].append(row)

for cam in CAMS:
    rows_by_cam[cam].sort(key=lambda r: int(r["usable_frame_index"]))

counts = {cam: len(rows_by_cam[cam]) for cam in CAMS}
common_n = min(counts.values())

print("Usable frames per camera:")
for cam in CAMS:
    print(f"  {cam}: {counts[cam]}")
print(f"Common synchronized frames: {common_n}")
print(f"Common duration: {common_n / FPS:.3f} s")

fieldnames = ["sample_index", "nominal_time_s"]
for cam in CAMS:
    fieldnames += [f"{cam}_video_path", f"{cam}_frame_index_in_video", f"{cam}_usable_frame_index"]

out_rows = []
for i in range(common_n):
    out = {"sample_index": i, "nominal_time_s": i / FPS}
    for cam in CAMS:
        r = rows_by_cam[cam][i]
        out[f"{cam}_video_path"] = r["video_path"]
        out[f"{cam}_frame_index_in_video"] = r["frame_index_in_video"]
        out[f"{cam}_usable_frame_index"] = r["usable_frame_index"]
    out_rows.append(out)

with open(sync_path, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(out_rows)

print(f"Saved: {sync_path}")
