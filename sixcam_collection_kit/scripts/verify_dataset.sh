#!/usr/bin/env bash
set -e
RUN=${1:-$(cat "$HOME/Downloads/latest_camera_dataset.txt")}
for f in "$RUN"/CAM_*/video.mkv; do
  echo "===== $f ====="
  ffprobe -v error -count_frames -select_streams v:0 \
    -show_entries stream=nb_read_frames,r_frame_rate,avg_frame_rate,duration \
    -of default=nokey=0:noprint_wrappers=1 "$f"
done

if [[ -d "$RUN/lidar" ]]; then
  echo "===== LiDAR ====="
  if [[ -f "$RUN/lidar/lidar_manifest.json" ]]; then
    python3 - "$RUN/lidar/lidar_manifest.json" <<'PY'
import json
import sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(f"bind_ip={manifest.get('bind_ip')}")
print(f"ports={manifest.get('ports')}")
print(f"metadata_only={manifest.get('metadata_only')}")
for stream in manifest.get("streams", []):
    print(
        f"{stream['name']}: packets={stream['packets']} "
        f"bytes={stream['bytes']} raw_dropped={stream['raw_dropped']}"
    )
PY
  else
    echo "Missing lidar/lidar_manifest.json"
  fi
fi

if [[ -d "$RUN/serial" ]]; then
  echo "===== Serial ====="
  for manifest_path in "$RUN"/serial/*_serial_manifest.json; do
    [[ -f "$manifest_path" ]] || continue
    python3 - "$manifest_path" <<'PY'
import json
import sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(
    f"{manifest.get('name')}: device={manifest.get('device')} "
    f"baud={manifest.get('baud')} chunks={manifest.get('chunks')} "
    f"bytes={manifest.get('bytes')}"
)
PY
  done
fi
