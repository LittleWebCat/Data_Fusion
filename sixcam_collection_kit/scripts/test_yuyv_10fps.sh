#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KIT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CONFIG_PATH="${CONFIG_PATH:-$KIT_DIR/config/config.env}"

if [[ ! -f "$CONFIG_PATH" ]]; then
  echo "Missing config file: $CONFIG_PATH" >&2
  exit 1
fi

# shellcheck source=/dev/null
source "$CONFIG_PATH"

DURATION="${1:-10}"
TEST_WIDTH="${TEST_WIDTH:-$WIDTH}"
TEST_HEIGHT="${TEST_HEIGHT:-$HEIGHT}"
TEST_FPS="${TEST_FPS:-10}"
TEST_FORMAT="${TEST_FORMAT:-YUYV}"
TEST_OUTPUT_ROOT="${TEST_OUTPUT_ROOT:-/tmp}"
TEST_TIMEOUT_GRACE="${TEST_TIMEOUT_GRACE:-15}"
TIMEOUT_SECONDS=$((DURATION + TEST_TIMEOUT_GRACE))
RUN="$TEST_OUTPUT_ROOT/yuyv_10fps_test_$(date +%Y%m%d_%H%M%S)"

CAM_NAMES=(CAM_FRONT CAM_FRONT_LEFT CAM_FRONT_RIGHT CAM_BACK CAM_BACK_LEFT CAM_BACK_RIGHT)
CAM_DEVS=("$CAM_FRONT" "$CAM_FRONT_LEFT" "$CAM_FRONT_RIGHT" "$CAM_BACK" "$CAM_BACK_LEFT" "$CAM_BACK_RIGHT")

mkdir -p "$RUN"

echo "YUYV 10 FPS camera test"
echo "Output: $RUN"
echo "Duration: ${DURATION}s"
echo "Wall-clock timeout: ${TIMEOUT_SECONDS}s"
echo "Mode: ${TEST_WIDTH}x${TEST_HEIGHT} ${TEST_FORMAT} @ ${TEST_FPS} FPS"
echo

cleanup() {
  for pid in "${PIDS[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
}
trap cleanup INT TERM

PIDS=()

for i in "${!CAM_NAMES[@]}"; do
  name="${CAM_NAMES[$i]}"
  dev="${CAM_DEVS[$i]}"
  mkdir -p "$RUN/$name"

  echo "Configuring $name $dev"
  v4l2-ctl -d "$dev" \
    --set-fmt-video=width="$TEST_WIDTH",height="$TEST_HEIGHT",pixelformat="$TEST_FORMAT" \
    --set-parm="$TEST_FPS"
  v4l2-ctl -d "$dev" --get-fmt-video
  v4l2-ctl -d "$dev" --get-parm
  echo

  timeout --signal=INT --kill-after=5s "${TIMEOUT_SECONDS}s" \
  ffmpeg -nostdin -hide_banner -loglevel warning \
    -f v4l2 \
    -input_format yuyv422 \
    -video_size "${TEST_WIDTH}x${TEST_HEIGHT}" \
    -framerate "$TEST_FPS" \
    -i "$dev" \
    -t "$DURATION" \
    -c:v mjpeg \
    -q:v "${MJPEG_QSCALE:-3}" \
    "$RUN/$name/video.mkv" \
    > "$RUN/$name/ffmpeg.log" 2>&1 &
  PIDS+=("$!")
done

status=0
for pid in "${PIDS[@]}"; do
  if ! wait "$pid"; then
    status=1
  fi
done

echo
echo "===== Results ====="
for name in "${CAM_NAMES[@]}"; do
  video="$RUN/$name/video.mkv"
  log="$RUN/$name/ffmpeg.log"
  echo "--- $name ---"
  if [[ -f "$video" ]]; then
    ffprobe -v error -count_frames -select_streams v:0 \
      -show_entries stream=nb_read_frames,r_frame_rate,avg_frame_rate,duration \
      -of default=nokey=0:noprint_wrappers=1 "$video" || status=1
  else
    echo "Missing output video"
    status=1
  fi
  if [[ -s "$log" ]]; then
    echo "ffmpeg log:"
    tail -20 "$log"
  fi
done

echo
if [[ "$status" -eq 0 ]]; then
  echo "PASS: YUYV test completed. Check frame counts against duration * ${TEST_FPS}."
else
  echo "FAIL: one or more cameras failed. See logs under $RUN" >&2
fi
echo "Output saved to: $RUN"
exit "$status"
