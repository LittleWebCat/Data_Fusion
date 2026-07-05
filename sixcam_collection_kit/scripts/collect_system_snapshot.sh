#!/usr/bin/env bash
set -e

OUT=${1:-system_snapshot_$(date +%Y%m%d_%H%M%S).txt}

{
  echo "sixcam_collection_kit system snapshot"
  echo "created_at=$(date --iso-8601=seconds)"
  echo "hostname=$(hostname)"
  echo

  echo "==== OS ===="
  if [[ -f /etc/os-release ]]; then
    cat /etc/os-release
  fi
  echo

  echo "==== Kernel ===="
  uname -a
  echo

  echo "==== Python ===="
  python3 --version || true
  echo

  echo "==== ffmpeg ===="
  ffmpeg -version 2>/dev/null | head -n 3 || true
  echo

  echo "==== v4l2-ctl ===="
  v4l2-ctl --version || true
  echo

  echo "==== USB devices ===="
  lsusb || true
  echo

  echo "==== /dev/video* ===="
  ls -l /dev/video* 2>/dev/null || true
  echo

  echo "==== Stable /dev/v4l/by-path names ===="
  ls -l /dev/v4l/by-path/ 2>/dev/null || true
  echo

  echo "==== v4l2 devices ===="
  v4l2-ctl --list-devices || true
  echo

  echo "==== Network interfaces ===="
  ip -br addr || true
  echo

  echo "==== Routes ===="
  ip route || true
  echo

  echo "==== Current config.env ===="
  if [[ -f config/config.env ]]; then
    sed 's/^/config: /' config/config.env
  else
    echo "config/config.env not found"
  fi
} > "$OUT"

echo "Wrote $OUT"
