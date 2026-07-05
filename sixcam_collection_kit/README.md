# Six-Camera Collection Kit

Portable Linux kit for collecting synchronized 6-camera USB video datasets.

Tested workflow from the original PC:

- 6 USB UVC cameras
- 1600x1200 MJPG @ 15 FPS
- frame-count recording
- 5 warm-up frames
- synchronized camera manifest
- estimated timestamp manifest
- 3x2 visual preview and saved-grid video

## 1. Install dependencies

On Ubuntu/Linux:

```bash
cd sixcam_collection_kit
./install_deps_ubuntu.sh
```

Manual dependencies:

```bash
sudo apt install ffmpeg v4l-utils python3 python3-pip
python3 -m pip install --user -r requirements.txt
```

For reproducing this kit on another PC, follow:

```bash
docs/NEW_PC_SETUP.md
```

Useful supplemental files:

```text
config/config.example.env
docs/NEW_PC_SETUP.md
docs/LIDAR_OUSTER_OS1.md
scripts/collect_system_snapshot.sh
```

## 2. Detect cameras on a new PC

```bash
cd sixcam_collection_kit
./scripts/check_cameras.sh
```

Use `v4l2-ctl --list-devices` to find the real image streams. For these cameras, the image streams are usually even-numbered devices:

```text
/dev/video0, /dev/video2, /dev/video4, /dev/video6, /dev/video8, /dev/video10
```

Metadata streams are usually odd-numbered devices and should not be used.

For stability across reboots, prefer `/dev/v4l/by-path/...video-index0` paths if available.

## 3. Edit camera config

Open:

```bash
nano config/config.env
```

Update these values if the new PC has different video devices:

```bash
CAM_FRONT=/dev/video0
CAM_FRONT_LEFT=/dev/video2
CAM_FRONT_RIGHT=/dev/video4
CAM_BACK=/dev/video6
CAM_BACK_LEFT=/dev/video8
CAM_BACK_RIGHT=/dev/video10
```

Default recording settings:

```bash
WIDTH=1600
HEIGHT=1200
FPS=15
FORMAT=MJPG
WARMUP_FRAMES=5
```

Optional LiDAR settings are in the same file. The current Ouster OS-1-128 setup
uses the wired interface IP `169.254.1.100`, sensor host `169.254.213.23`, lidar
UDP port `7502`, and IMU UDP port `7503`:

```bash
ENABLE_LIDAR=1
LIDAR_BIND_IP=169.254.1.100
LIDAR_SENSOR_HOST=169.254.213.23
LIDAR_UDP_PORTS="7502 7503"
LIDAR_METADATA_ONLY=0
```

Set `ENABLE_LIDAR=0` for camera-only recording. Set `LIDAR_METADATA_ONLY=1` for
lowest disk load timing capture without raw point-cloud packets.

## 4. Preview all cameras

```bash
python3 scripts/preview_6cam.py
```

Press `q` or `ESC` to quit.

Cover each physical camera with your hand and confirm the label is correct. If labels are wrong, update `config/config.env`.

## 5. Record 6 cameras

Basic frame-count recording:

```bash
./scripts/record_6cam_frames.sh 30
```

Timestamp-aware recording, recommended for fusion:

```bash
./scripts/record_6cam_time.sh 30
```

When `ENABLE_LIDAR=1`, the same command also records LiDAR UDP packets for the
full camera capture. LiDAR files are saved under:

```text
$LATEST/lidar/
```

Typical outputs:

```text
lidar_7502_udp.csv
lidar_7502_udp.bin
lidar_7503_udp.csv
lidar_7503_udp.bin
lidar_manifest.json
ouster_metadata.json
```

The CSV files contain `monotonic_ns` and `system_time_ns` timestamps for fusion.
The `.bin` files contain raw UDP payloads for point-cloud decoding.

The latest dataset path is saved to:

```bash
~/Downloads/latest_camera_dataset.txt
```

## 6. Verify recording

```bash
LATEST=$(cat ~/Downloads/latest_camera_dataset.txt)
./scripts/verify_dataset.sh "$LATEST"
```

For 30 seconds at 15 FPS with 5 warm-up frames, expected frame count is about:

```text
30 * 15 + 5 = 455 frames
```

Small differences like 454/455 are acceptable if only startup MJPEG warnings appear.

## 7. Generate manifests

```bash
LATEST=$(cat ~/Downloads/latest_camera_dataset.txt)
python3 scripts/make_6cam_manifest.py "$LATEST"
python3 scripts/make_6cam_sync_manifest.py "$LATEST"
```

If you used `record_6cam_time.sh`, also run:

```bash
python3 scripts/make_6cam_timestamp_manifest.py "$LATEST"
```

Outputs:

```text
camera_manifest.csv
camera_sync_manifest.csv
camera_sync_timestamp_manifest.csv
```

`camera_sync_timestamp_manifest.csv` contains estimated `monotonic_ns` and `system_time_ns` for each synchronized 6-camera sample. These are estimated timestamps, not hardware timestamps.

## 8. Extract synchronized sample images

```bash
LATEST=$(cat ~/Downloads/latest_camera_dataset.txt)
python3 scripts/extract_6cam_sample.py "$LATEST" 0
python3 scripts/extract_6cam_sample.py "$LATEST" 100
python3 scripts/extract_6cam_sample.py "$LATEST" 300
```

Open the sample image:

```bash
xdg-open "$LATEST/sync_sample_000100.jpg"
```

## 9. Make one 3x2 grid video from saved videos

```bash
LATEST=$(cat ~/Downloads/latest_camera_dataset.txt)
./scripts/make_sixcam_grid.sh "$LATEST"
xdg-open "$LATEST/sixcam_grid.mp4"
```

## 10. Recommended workflow on a new PC

```bash
cd sixcam_collection_kit
./install_deps_ubuntu.sh
./scripts/check_cameras.sh
nano config/config.env
python3 scripts/preview_6cam.py
./scripts/record_6cam_time.sh 30
LATEST=$(cat ~/Downloads/latest_camera_dataset.txt)
./scripts/verify_dataset.sh "$LATEST"
python3 scripts/make_6cam_manifest.py "$LATEST"
python3 scripts/make_6cam_sync_manifest.py "$LATEST"
python3 scripts/make_6cam_timestamp_manifest.py "$LATEST"
python3 scripts/extract_6cam_sample.py "$LATEST" 100
./scripts/make_sixcam_grid.sh "$LATEST"
```

## Notes for sensor fusion

This kit records cameras and optional LiDAR using the same system clock convention:

```text
monotonic_ns, system_time_ns, sensor fields...
```

Align each LiDAR/IMU/GPS measurement to camera samples using nearest
`estimated_monotonic_ns`.

The current camera timestamps are estimated from:

```text
all_ffmpeg_started + (warmup_frames + sample_index) / FPS
```

For research-grade time synchronization, the next improvement is true V4L2 buffer timestamp logging or hardware-triggered cameras.
