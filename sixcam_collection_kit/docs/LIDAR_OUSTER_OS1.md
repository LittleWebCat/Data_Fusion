# Ouster OS-1-128 LiDAR Notes

The tested LiDAR is an Ouster OS-1-128.

Known working network values:

```text
PC LiDAR interface IP: 169.254.1.100/16
Sensor IP:             169.254.213.23
LiDAR UDP port:        7502
IMU UDP port:          7503
LiDAR mode:            1024x10
Profile:               RNG19_RFL8_SIG16_NIR16
```

The kit records:

```text
lidar/lidar_7502_udp.csv  packet timestamps for LiDAR packets
lidar/lidar_7502_udp.bin  raw LiDAR UDP payloads
lidar/lidar_7503_udp.csv  packet timestamps for IMU packets
lidar/lidar_7503_udp.bin  raw IMU UDP payloads
lidar/ouster_metadata.json sensor calibration/format metadata
```

## Confirm sensor access

```bash
curl http://169.254.213.23/api/v1/sensor/metadata
```

The response should include `prod_line`, `beam_intrinsics`, and
`lidar_data_format`.

## Confirm UDP data

Run a short collection:

```bash
bash scripts/record_6cam_time.sh 10
LATEST=$(cat ~/Downloads/latest_camera_dataset.txt)
bash scripts/verify_dataset.sh "$LATEST"
```

Expected LiDAR packet rates are approximately:

```text
7502: 640 packets/s
7503: 100 packets/s
```

## Decode point clouds

Install the official Ouster SDK:

```bash
python3 -m pip install --user ouster-sdk
```

The raw `.bin` files are the kit's lightweight capture format. To decode point
clouds, use `lidar/ouster_metadata.json` with an Ouster SDK script, or export a
PCAP using a compatible converter.

For camera/LiDAR matching, use nearest `monotonic_ns` between:

```text
camera_sync_timestamp_manifest.csv
lidar/lidar_7502_udp.csv
```

The current camera timestamps are estimated from ffmpeg start time and FPS. This
is good enough for synchronized collection checks and coarse fusion. For
research-grade timing, use hardware triggers or true V4L2 buffer timestamps.
