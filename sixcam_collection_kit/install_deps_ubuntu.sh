#!/usr/bin/env bash
set -e
sudo apt update
sudo apt install -y ffmpeg v4l-utils python3 python3-pip
python3 -m pip install --user -r requirements.txt
