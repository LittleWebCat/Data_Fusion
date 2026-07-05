#!/usr/bin/env bash
set -e
printf "\n==== USB devices ===="; echo
lsusb || true
printf "\n==== /dev/video* ===="; echo
ls -l /dev/video* 2>/dev/null || true
printf "\n==== v4l2 devices ===="; echo
v4l2-ctl --list-devices
printf "\n==== Stable by-path names ===="; echo
ls -l /dev/v4l/by-path/ 2>/dev/null || true
