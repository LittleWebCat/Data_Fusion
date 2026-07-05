#!/usr/bin/env python3
import csv
import os
import sys
from pathlib import Path

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

if len(sys.argv) != 2:
    print("Usage: python3 scripts/make_6cam_timestamp_manifest.py /path/to/dataset")
    sys.exit(1)

run_dir = Path(sys.argv[1]).expanduser().resolve()
clock_path = run_dir / "clock_events.csv"
sync_path = run_dir / "camera_sync_manifest.csv"
out_path = run_dir / "camera_sync_timestamp_manifest.csv"

events = {}
with open(clock_path, "r") as f:
    reader = csv.DictReader(f)
    for row in reader:
        events[row["event"]] = row

if "all_ffmpeg_started" not in events:
    raise RuntimeError("Missing all_ffmpeg_started in clock_events.csv. Use record_6cam_time.sh.")

base_mono_ns = int(events["all_ffmpeg_started"]["monotonic_ns"])
base_system_ns = int(events["all_ffmpeg_started"]["system_time_ns"])

print("Base event: all_ffmpeg_started")
print(f"base_monotonic_ns={base_mono_ns}")
print(f"base_system_time_ns={base_system_ns}")
print(f"warmup_offset_s={WARMUP_FRAMES / FPS:.6f}")

with open(sync_path, "r") as f:
    rows = list(csv.DictReader(f))

fieldnames = list(rows[0].keys()) + [
    "estimated_monotonic_ns",
    "estimated_system_time_ns",
    "estimated_time_s_from_ffmpeg_start",
    "estimated_usable_time_s",
    "timestamp_method",
]

out_rows = []
for row in rows:
    sample_index = int(row["sample_index"])
    time_from_ffmpeg_start_s = (WARMUP_FRAMES + sample_index) / FPS
    dt_ns = int(time_from_ffmpeg_start_s * 1_000_000_000)
    row["estimated_monotonic_ns"] = base_mono_ns + dt_ns
    row["estimated_system_time_ns"] = base_system_ns + dt_ns
    row["estimated_time_s_from_ffmpeg_start"] = time_from_ffmpeg_start_s
    row["estimated_usable_time_s"] = sample_index / FPS
    row["timestamp_method"] = "estimated_from_all_ffmpeg_started_plus_warmup_plus_sample_index_over_fps"
    out_rows.append(row)

with open(out_path, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(out_rows)

print(f"Saved: {out_path}")
print(f"Rows: {len(out_rows)}")
print(f"Usable duration: {len(out_rows) / FPS:.3f} s")
