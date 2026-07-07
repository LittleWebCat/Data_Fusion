#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KIT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CONFIG_PATH="${CONFIG_PATH:-$KIT_DIR/config/config.env}"

if [[ ! -f "$CONFIG_PATH" ]]; then
  echo "Missing config file: $CONFIG_PATH" >&2
  exit 1
fi

# shellcheck source=/dev/null
source "$CONFIG_PATH"

CAM_NAMES=(CAM_FRONT CAM_FRONT_LEFT CAM_FRONT_RIGHT CAM_BACK CAM_BACK_LEFT CAM_BACK_RIGHT)
CAM_DEVS=("$CAM_FRONT" "$CAM_FRONT_LEFT" "$CAM_FRONT_RIGHT" "$CAM_BACK" "$CAM_BACK_LEFT" "$CAM_BACK_RIGHT")

ENABLE_LIDAR=${ENABLE_LIDAR:-0}
LIDAR_BIND_IP=${LIDAR_BIND_IP:-0.0.0.0}
LIDAR_SENSOR_HOST=${LIDAR_SENSOR_HOST:-}
LIDAR_UDP_PORTS=${LIDAR_UDP_PORTS:-}
LIDAR_RCVBUF=${LIDAR_RCVBUF:-16777216}
LIDAR_WRITER_QUEUE=${LIDAR_WRITER_QUEUE:-8192}
LIDAR_METADATA_ONLY=${LIDAR_METADATA_ONLY:-0}
CAMERA_CAPTURE_FPS=${CAMERA_CAPTURE_FPS:-$FPS}
MJPEG_QSCALE=${MJPEG_QSCALE:-3}

now_dataset_dir() {
  mkdir -p "$DATA_ROOT"
  echo "$DATA_ROOT/dataset_$(date +%Y%m%d_%H%M%S)"
}

configure_camera() {
  local dev="$1"
  echo "Configuring $dev -> ${WIDTH}x${HEIGHT} $FORMAT capture @ ${CAMERA_CAPTURE_FPS} FPS, output @ ${FPS} FPS"
  v4l2-ctl -d "$dev" --set-fmt-video=width=$WIDTH,height=$HEIGHT,pixelformat=$FORMAT --set-parm=$CAMERA_CAPTURE_FPS
  v4l2-ctl -d "$dev" -c power_line_frequency=$POWER_LINE_FREQUENCY >/dev/null 2>&1 || true
}

log_time_event() {
  local run="$1"
  local event="$2"
  local note="$3"
  python3 - "$event" "$note" >> "$run/clock_events.csv" <<'PY'
import sys, time
print(f"{sys.argv[1]},{time.monotonic_ns()},{time.time_ns()},{sys.argv[2]}")
PY
}

start_lidar_recorder() {
  local run="$1"
  LIDAR_PID=""

  if [[ "$ENABLE_LIDAR" != "1" ]]; then
    return 0
  fi
  if [[ -z "$LIDAR_UDP_PORTS" ]]; then
    echo "ENABLE_LIDAR=1 but LIDAR_UDP_PORTS is empty" >&2
    exit 1
  fi

  local lidar_dir="$run/lidar"
  mkdir -p "$lidar_dir"

  if [[ -n "$LIDAR_SENSOR_HOST" ]] && command -v curl >/dev/null 2>&1; then
    curl --max-time 5 -fsS \
      "http://$LIDAR_SENSOR_HOST/api/v1/sensor/metadata" \
      -o "$lidar_dir/ouster_metadata.json" \
      > "$lidar_dir/metadata_fetch.log" 2>&1 || true
  fi

  local args=(
    "$SCRIPT_DIR/record_lidar_udp.py"
    --output-dir "$lidar_dir"
    --bind "$LIDAR_BIND_IP"
    --rcvbuf "$LIDAR_RCVBUF"
    --writer-queue "$LIDAR_WRITER_QUEUE"
  )

  local port
  for port in $LIDAR_UDP_PORTS; do
    args+=(--port "$port")
  done

  if [[ "$LIDAR_METADATA_ONLY" == "1" ]]; then
    args+=(--metadata-only)
  fi

  echo "Starting LiDAR recorder on $LIDAR_BIND_IP ports: $LIDAR_UDP_PORTS"
  python3 "${args[@]}" > "$lidar_dir/lidar_recorder.log" 2>&1 &
  LIDAR_PID=$!
  echo "$LIDAR_PID" > "$lidar_dir/lidar_recorder.pid"
  log_time_event "$run" "lidar_recorder_started" "pid=$LIDAR_PID ports=$LIDAR_UDP_PORTS"
}

stop_lidar_recorder() {
  local run="$1"

  if [[ -z "${LIDAR_PID:-}" ]]; then
    return 0
  fi
  if ! kill -0 "$LIDAR_PID" 2>/dev/null; then
    return 0
  fi

  log_time_event "$run" "lidar_recorder_stop_requested" "pid=$LIDAR_PID"
  kill -TERM "$LIDAR_PID" 2>/dev/null || true
  wait "$LIDAR_PID" || true
  log_time_event "$run" "lidar_recorder_stopped" "pid=$LIDAR_PID"
}
