#!/usr/bin/env bash
set -e
RUN=${1:-$(cat "$HOME/Downloads/latest_camera_dataset.txt")}
for f in "$RUN"/CAM_*/video.mkv; do
  echo "===== $f ====="
  ffprobe -v error -count_frames -select_streams v:0 \
    -show_entries stream=nb_read_frames,r_frame_rate,avg_frame_rate,duration \
    -of default=nokey=0:noprint_wrappers=1 "$f"
done
