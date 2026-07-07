#!/usr/bin/env bash
set -euo pipefail

RUN="${1:-}"
if [[ -z "$RUN" ]]; then
  LATEST_FILE="$HOME/Downloads/latest_camera_dataset.txt"
  if [[ ! -f "$LATEST_FILE" ]]; then
    echo "FAIL: missing latest dataset pointer: $LATEST_FILE" >&2
    exit 1
  fi
  RUN="$(cat "$LATEST_FILE")"
fi

if [[ ! -d "$RUN" ]]; then
  echo "FAIL: dataset folder does not exist: $RUN" >&2
  exit 1
fi

echo "Dataset: $RUN"
echo

echo "===== Camera Videos ====="
camera_count=0
missing_camera=0
for camera_dir in "$RUN"/CAM_*; do
  if [[ ! -d "$camera_dir" ]]; then
    continue
  fi

  camera_count=$((camera_count + 1))
  video="$camera_dir/video.mkv"
  name="$(basename "$camera_dir")"
  if [[ ! -f "$video" ]]; then
    echo "$name: FAIL missing video.mkv"
    missing_camera=1
    continue
  fi

  echo "--- $name ---"
  ffprobe -v error -count_frames -select_streams v:0 \
    -show_entries stream=nb_read_frames,r_frame_rate,avg_frame_rate,duration \
    -of default=nokey=0:noprint_wrappers=1 "$video"
done

if [[ "$camera_count" -eq 0 ]]; then
  echo "FAIL: no CAM_* folders found"
  missing_camera=1
fi

echo
echo "===== LiDAR ====="
lidar_status=0
if [[ ! -d "$RUN/lidar" ]]; then
  echo "FAIL: missing lidar folder"
  lidar_status=1
elif [[ ! -f "$RUN/lidar/lidar_manifest.json" ]]; then
  echo "FAIL: missing lidar/lidar_manifest.json"
  lidar_status=1
else
  python3 - "$RUN/lidar/lidar_manifest.json" <<'PY'
import json
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
lidar_dir = manifest_path.parent
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

print(f"bind_ip={manifest.get('bind_ip')}")
print(f"ports={manifest.get('ports')}")
print(f"metadata_only={manifest.get('metadata_only')}")

streams = manifest.get("streams", [])
if not streams:
    print("FAIL: no LiDAR streams recorded")
    raise SystemExit(1)

ok = True
for stream in streams:
    name = stream.get("name", "unknown")
    packets = int(stream.get("packets") or 0)
    byte_count = int(stream.get("bytes") or 0)
    raw_dropped = int(stream.get("raw_dropped") or 0)
    metadata_csv = stream.get("metadata_csv")
    binary_file = stream.get("binary_file")

    print(f"{name}: packets={packets} bytes={byte_count} raw_dropped={raw_dropped}")

    if packets <= 0:
        print(f"FAIL: {name} has zero packets")
        ok = False
    if raw_dropped != 0:
        print(f"FAIL: {name} dropped raw packets")
        ok = False
    if metadata_csv and not (lidar_dir / metadata_csv).is_file():
        print(f"FAIL: missing {metadata_csv}")
        ok = False
    if binary_file and not (lidar_dir / binary_file).is_file():
        print(f"FAIL: missing {binary_file}")
        ok = False

if (lidar_dir / "ouster_metadata.json").is_file():
    print("ouster_metadata.json=present")
else:
    print("WARN: ouster_metadata.json missing")

raise SystemExit(0 if ok else 1)
PY
  lidar_status=$?
fi

echo
echo "===== LiDAR Files ====="
if [[ -d "$RUN/lidar" ]]; then
  ls -lh "$RUN/lidar"
fi

echo
if [[ "$missing_camera" -eq 0 && "$lidar_status" -eq 0 ]]; then
  echo "PASS: camera and LiDAR verification completed"
else
  echo "FAIL: collection verification found problems" >&2
  exit 1
fi
