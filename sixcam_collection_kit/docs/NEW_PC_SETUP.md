# New PC Setup

This checklist is for copying `sixcam_collection_kit` to another Ubuntu/Linux
PC and reproducing the 6-camera + Ouster LiDAR collection workflow.

## 1. Install dependencies

```bash
cd sixcam_collection_kit
./install_deps_ubuntu.sh
```

Optional, only needed for Ouster point-cloud decoding/rendering:

```bash
python3 -m pip install --user ouster-sdk
```

## 2. Copy the config template

```bash
cp config/config.example.env config/config.env
```

Edit:

```bash
nano config/config.env
```

## 3. Map the six cameras

Run:

```bash
./scripts/check_cameras.sh
```

Use the real image streams, usually even-numbered devices such as:

```text
/dev/video0, /dev/video2, /dev/video4, /dev/video6, /dev/video8, /dev/video10
```

For stable mapping across reboot, prefer paths under:

```text
/dev/v4l/by-path/
```

Update these in `config/config.env`:

```bash
CAM_FRONT=...
CAM_FRONT_LEFT=...
CAM_FRONT_RIGHT=...
CAM_BACK=...
CAM_BACK_LEFT=...
CAM_BACK_RIGHT=...
```

Then preview:

```bash
python3 scripts/preview_6cam.py
```

Cover each physical camera by hand and confirm the label.

## 4. Configure the LiDAR network

The current Ouster OS-1-128 setup uses:

```text
PC LiDAR NIC IP: 169.254.1.100/16
Sensor IP:       169.254.213.23
LiDAR port:      7502
IMU port:        7503
```

Check the new PC network interfaces:

```bash
ip -br addr
```

If the wired LiDAR interface does not have `169.254.1.100/16`, set it with your
network manager or temporarily with:

```bash
sudo ip addr add 169.254.1.100/16 dev YOUR_INTERFACE
sudo ip link set YOUR_INTERFACE up
```

Confirm the sensor metadata endpoint:

```bash
curl http://169.254.213.23/api/v1/sensor/metadata
```

Update these in `config/config.env` if needed:

```bash
ENABLE_LIDAR=1
LIDAR_BIND_IP=169.254.1.100
LIDAR_SENSOR_HOST=169.254.213.23
LIDAR_UDP_PORTS="7502 7503"
```

## 5. Configure PC-attached GPS/IMU serial devices

If the GPS or IMU is connected directly to the PC over USB serial, inspect the
device paths:

```bash
ls -l /dev/serial/by-id/ /dev/ttyUSB* /dev/ttyACM*
```

Prefer `/dev/serial/by-id/...` paths because `/dev/ttyUSB0` and
`/dev/ttyACM0` can change after unplug/reboot. Update `config/config.env`:

```bash
ENABLE_GPS=1
GPS_SERIAL_DEV=/dev/serial/by-id/usb-your-gps
GPS_BAUD=115200

ENABLE_IMU=1
IMU_SERIAL_DEV=/dev/serial/by-id/usb-your-imu
IMU_BAUD=115200
```

Set either `ENABLE_GPS=0` or `ENABLE_IMU=0` if that device is not connected.

## 6. Record a test dataset

```bash
bash scripts/record_6cam_time.sh 10
LATEST=$(cat ~/Downloads/latest_camera_dataset.txt)
bash scripts/verify_dataset.sh "$LATEST"
```

Expected:

- all six cameras have the same frame count
- LiDAR `7502` and `7503` packet counts are nonzero
- `raw_dropped=0` for both LiDAR streams
- enabled GPS/IMU serial streams have nonzero `chunks` and `bytes`

## 7. Normal collection

```bash
bash scripts/record_6cam_time.sh 30
LATEST=$(cat ~/Downloads/latest_camera_dataset.txt)
bash scripts/verify_dataset.sh "$LATEST"
```

Dataset layout:

```text
dataset_YYYYMMDD_HHMMSS/
  CAM_FRONT/video.mkv
  CAM_FRONT_LEFT/video.mkv
  CAM_FRONT_RIGHT/video.mkv
  CAM_BACK/video.mkv
  CAM_BACK_LEFT/video.mkv
  CAM_BACK_RIGHT/video.mkv
  lidar/lidar_7502_udp.csv
  lidar/lidar_7502_udp.bin
  lidar/lidar_7503_udp.csv
  lidar/lidar_7503_udp.bin
  lidar/lidar_manifest.json
  lidar/ouster_metadata.json
  serial/gps_serial.csv
  serial/gps_serial.bin
  serial/gps_serial_manifest.json
  serial/imu_serial.csv
  serial/imu_serial.bin
  serial/imu_serial_manifest.json
  clock_events.csv
  meta.txt
```

## 8. Generate camera manifests

```bash
python3 scripts/make_6cam_manifest.py "$LATEST"
python3 scripts/make_6cam_sync_manifest.py "$LATEST"
python3 scripts/make_6cam_timestamp_manifest.py "$LATEST"
```

Use `camera_sync_timestamp_manifest.csv` and `lidar/lidar_7502_udp.csv` to align
camera samples and LiDAR packets by nearest `monotonic_ns`.
