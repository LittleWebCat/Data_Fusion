#!/usr/bin/env python3
import csv
import os
import subprocess
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
CAMS = ["CAM_FRONT", "CAM_FRONT_LEFT", "CAM_FRONT_RIGHT", "CAM_BACK", "CAM_BACK_LEFT", "CAM_BACK_RIGHT"]


def frame_pts_times(video_path: Path) -> list[float]:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "frame=best_effort_timestamp_time",
        "-of",
        "csv=p=0",
        str(video_path),
    ]
    output = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL)
    pts_times = []
    for line in output.splitlines():
        value = line.split(",", 1)[0].strip()
        if value and value != "N/A":
            pts_times.append(float(value))
    return pts_times

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

pts_by_video = {}
for row in rows[:1]:
    for cam in CAMS:
        video_path = Path(row[f"{cam}_video_path"])
        pts_by_video[str(video_path)] = frame_pts_times(video_path)

fieldnames = list(rows[0].keys()) + [
    "estimated_monotonic_ns",
    "estimated_system_time_ns",
    "estimated_time_s_from_ffmpeg_start",
    "estimated_usable_time_s",
    "timestamp_method",
]
for cam in CAMS:
    fieldnames += [
        f"{cam}_pts_time_s",
        f"{cam}_estimated_monotonic_ns",
        f"{cam}_estimated_system_time_ns",
    ]

out_rows = []
first_sample_time_s = None
for row in rows:
    sample_index = int(row["sample_index"])
    mono_values = []
    system_values = []
    pts_values = []

    for cam in CAMS:
        frame_index = int(row[f"{cam}_frame_index_in_video"])
        video_path = row[f"{cam}_video_path"]
        pts_times = pts_by_video[video_path]
        if frame_index >= len(pts_times):
            raise RuntimeError(f"{cam} frame index {frame_index} is outside {video_path}")

        pts_s = pts_times[frame_index]
        event_name = f"ffmpeg_start_{cam}"
        cam_base_mono_ns = int(events.get(event_name, events["all_ffmpeg_started"])["monotonic_ns"])
        cam_base_system_ns = int(events.get(event_name, events["all_ffmpeg_started"])["system_time_ns"])
        cam_mono_ns = cam_base_mono_ns + int(pts_s * 1_000_000_000)
        cam_system_ns = cam_base_system_ns + int(pts_s * 1_000_000_000)

        row[f"{cam}_pts_time_s"] = f"{pts_s:.6f}"
        row[f"{cam}_estimated_monotonic_ns"] = cam_mono_ns
        row[f"{cam}_estimated_system_time_ns"] = cam_system_ns
        mono_values.append(cam_mono_ns)
        system_values.append(cam_system_ns)
        pts_values.append(pts_s)

    row["estimated_monotonic_ns"] = int(sum(mono_values) / len(mono_values))
    row["estimated_system_time_ns"] = int(sum(system_values) / len(system_values))
    row["estimated_time_s_from_ffmpeg_start"] = f"{sum(pts_values) / len(pts_values):.6f}"
    if first_sample_time_s is None:
        first_sample_time_s = float(row["estimated_time_s_from_ffmpeg_start"])
    row["estimated_usable_time_s"] = (
        f"{float(row['estimated_time_s_from_ffmpeg_start']) - first_sample_time_s:.6f}"
    )
    row["timestamp_method"] = "estimated_from_per_camera_ffmpeg_start_event_plus_video_frame_pts"
    out_rows.append(row)

with open(out_path, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(out_rows)

print(f"Saved: {out_path}")
print(f"Rows: {len(out_rows)}")
if out_rows:
    print(f"Usable duration: {out_rows[-1]['estimated_usable_time_s']} s")
