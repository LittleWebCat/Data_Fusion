#!/usr/bin/env bash
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

DURATION=${1:-30}
TARGET_FRAMES=$((DURATION * FPS))
NFRAMES=$((TARGET_FRAMES + WARMUP_FRAMES))

pkill -f "ffmpeg.*v4l2" 2>/dev/null || true
sleep 1

RUN=$(now_dataset_dir)
mkdir -p "$RUN"/logs
for name in "${CAM_NAMES[@]}"; do mkdir -p "$RUN/$name"; done

echo "$RUN" > "$DATA_ROOT/latest_camera_dataset.txt"
echo "Saving to: $RUN"
echo "Target duration: ${DURATION}s"
echo "Target usable frames: $TARGET_FRAMES"
echo "Recorded frames including warmup: $NFRAMES"

echo "event,monotonic_ns,system_time_ns,note" > "$RUN/clock_events.csv"
log_time_event "$RUN" "script_start" "record_6cam_time"

for dev in "${CAM_DEVS[@]}"; do
  configure_camera "$dev"
  log_time_event "$RUN" "camera_configured" "$dev"
done

cat > "$RUN/meta.txt" <<META
created_at=$(date --iso-8601=seconds)
width=$WIDTH
height=$HEIGHT
fps=$FPS
format=$FORMAT
duration_s=$DURATION
target_frames=$TARGET_FRAMES
warmup_frames=$WARMUP_FRAMES
recorded_frames=$NFRAMES
CAM_FRONT=$CAM_FRONT
CAM_FRONT_LEFT=$CAM_FRONT_LEFT
CAM_FRONT_RIGHT=$CAM_FRONT_RIGHT
CAM_BACK=$CAM_BACK
CAM_BACK_LEFT=$CAM_BACK_LEFT
CAM_BACK_RIGHT=$CAM_BACK_RIGHT
time_base=python time.monotonic_ns and time.time_ns
recording_method=ffmpeg frame-count -frames:v, -c copy
note=Frame timestamps are estimated from all_ffmpeg_started plus (warmup_frames+sample_index)/fps. Not hardware timestamps.
META

start_cam () {
  local name="$1"
  local dev="$2"
  echo "Starting $name from $dev"
  log_time_event "$RUN" "ffmpeg_start_$name" "$dev"
  ffmpeg -nostdin -hide_banner -loglevel warning \
    -fflags +genpts+discardcorrupt \
    -f v4l2 \
    -input_format mjpeg \
    -video_size ${WIDTH}x${HEIGHT} \
    -framerate "$FPS" \
    -i "$dev" \
    -frames:v "$NFRAMES" \
    -c copy \
    "$RUN/$name/video.mkv" \
    > "$RUN/$name/ffmpeg.log" 2>&1 &
}

log_time_event "$RUN" "record_start" "before_starting_ffmpeg"
for i in "${!CAM_NAMES[@]}"; do
  start_cam "${CAM_NAMES[$i]}" "${CAM_DEVS[$i]}"
done
log_time_event "$RUN" "all_ffmpeg_started" "all_6_camera_processes_spawned"

wait
log_time_event "$RUN" "record_end" "all_ffmpeg_finished"

echo "Finished."
echo "Dataset saved to: $RUN"
echo "Latest dataset path saved to: $DATA_ROOT/latest_camera_dataset.txt"
