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

now_dataset_dir() {
  mkdir -p "$DATA_ROOT"
  echo "$DATA_ROOT/dataset_$(date +%Y%m%d_%H%M%S)"
}

configure_camera() {
  local dev="$1"
  echo "Configuring $dev -> ${WIDTH}x${HEIGHT} $FORMAT @ ${FPS} FPS"
  v4l2-ctl -d "$dev" --set-fmt-video=width=$WIDTH,height=$HEIGHT,pixelformat=$FORMAT --set-parm=$FPS
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
