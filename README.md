# Local Camera Viewer

Small Python app that finds connected cameras and shows all working camera feeds in one window.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
python camera_viewer.py
```

For several USB cameras on the same hub, start by listing the detected capture nodes:

```bash
python3 camera_viewer.py --list
```

To inspect negotiated camera modes and read failures:

```bash
python3 camera_viewer.py --probe --width 320 --height 240 --fps 10 --fourcc MJPG
```

Then run with MJPEG and modest FPS to reduce USB bandwidth:

```bash
python3 camera_viewer.py --width 640 --height 480 --fps 15 --fourcc MJPG
```

The default six-camera layout is:

```text
video4=fL   video10=f   video8=fR
video6=bL   video0=b    video2=bR
```

To override it:

```bash
python3 camera_viewer.py --layout "4=fL,10=f,8=fR/6=bL,0=b,2=bR"
```

If some cameras do not open, try a lower bandwidth mode:

```bash
python3 camera_viewer.py --width 320 --height 240 --fps 10 --fourcc MJPG
```

## Data Collection

For aligned recording, use `--record-dir`. The app captures each cycle with
`grab()` across all cameras first, then `retrieve()` for decoding. This reduces
software timestamp skew compared with reading one full frame at a time.

```bash
python3 camera_viewer.py \
  --width 640 --height 480 --fps 15 --fourcc MJPG --buffer-size 1 \
  --record-dir data --duration 60 --warmup-seconds 1.5
```

For lowest display overhead during collection:

```bash
python3 camera_viewer.py \
  --width 640 --height 480 --fps 15 --fourcc MJPG --buffer-size 1 \
  --record-dir data --duration 60 --warmup-seconds 1.5 --no-preview
```

To record a UDP LiDAR stream in the same session, add the LiDAR UDP port:

```bash
python3 camera_viewer.py \
  --width 320 --height 240 --fps 10 --fourcc MJPG --buffer-size 1 \
  --record-dir data --duration 30 --warmup-seconds 1.5 --no-preview \
  --lidar-udp-port 2368
```

The LiDAR recorder uses the same `monotonic_ns` clock as camera metadata. It
stores raw packets in `lidar_udp.bin` and packet timestamps in `lidar_udp.csv`.
Use `--lidar-bind` if the LiDAR must bind to a specific local interface IP.

If zero LiDAR packets are recorded, probe common LiDAR UDP ports first:

```bash
python3 probe_lidar_udp.py --duration 10
```

Loopback sources such as `127.0.0.1` are local machine traffic, not the LiDAR,
and are ignored by default.

If your LiDAR-facing interface has a fixed IP, bind to it:

```bash
python3 probe_lidar_udp.py --bind 192.168.1.100 --duration 10
```

When the probe finds packets, use that destination port as `--lidar-udp-port`.

You can also probe a custom port range:

```bash
python3 probe_lidar_udp.py --ports 2000-9000 --duration 10
```

If no UDP packets appear, sniff the physical interface to discover whether any
UDP traffic is arriving at all:

```bash
sudo python3 sniff_udp.py eno1 --duration 10
sudo python3 sniff_udp.py usb0 --duration 10
```

Use the destination port printed by `sniff_udp.py` as `--lidar-udp-port`.
For the current AGX setup, LiDAR traffic has been seen on `eno1` from
`169.254.213.23` to local ports `47131` and `46075`.

For cleaner LiDAR-only sniffing:

```bash
sudo python3 sniff_udp.py eno1 --source-ip 169.254.213.23 --duration 10
```

For this setup, record both LiDAR UDP streams with:

```bash
python3 camera_viewer.py \
  --width 320 --height 240 --fps 10 --fourcc MJPG --buffer-size 1 \
  --record-dir data --duration 30 --warmup-seconds 1.5 --no-preview \
  --lidar-bind 169.254.1.100 \
  --lidar-udp-port 47131 --lidar-udp-port 46075
```

For timing tests with lower disk load, record LiDAR metadata only:

```bash
python3 camera_viewer.py \
  --width 320 --height 240 --fps 10 --fourcc MJPG --buffer-size 1 \
  --record-dir data --duration 30 --warmup-seconds 1.5 --no-preview \
  --lidar-bind 169.254.1.100 \
  --lidar-udp-port 47131 --lidar-udp-port 46075 \
  --lidar-metadata-only
```

For full raw LiDAR payloads, omit `--lidar-metadata-only`. Raw packets are sent
to a separate writer process through a bounded queue so disk I/O is isolated
from camera capture:

```bash
python3 camera_viewer.py \
  --width 320 --height 240 --fps 10 --fourcc MJPG --buffer-size 1 \
  --record-dir data --duration 30 --warmup-seconds 1.5 --no-preview \
  --lidar-bind 169.254.1.100 \
  --lidar-udp-port 47131 --lidar-udp-port 46075 \
  --lidar-writer-queue 2048
```

Check `raw_dropped` in `analyze_lidar.py`. If it is nonzero, the raw LiDAR
writer could not keep up; increase `--lidar-writer-queue` or write to faster
storage.

The recorder grabs cameras in parallel by default to reduce software timestamp
spread. To compare against one-at-a-time grabbing:

```bash
python3 camera_viewer.py \
  --width 640 --height 480 --fps 15 --fourcc MJPG --buffer-size 1 \
  --record-dir data --duration 10 --warmup-seconds 1.5 --no-preview --sequential-grab
```

If one of the expected layout cameras is missing, the app will print it. For
example, missing `f (video10)` during recording usually means bandwidth or
device-open contention. Try this lower-bandwidth six-camera test:

```bash
python3 camera_viewer.py \
  --width 320 --height 240 --fps 10 --fourcc MJPG --buffer-size 1 \
  --record-dir data --duration 30 --warmup-seconds 1.5 --no-preview
```

Your first few cycles may have startup skew while cameras settle. By default,
`--warmup-seconds 1.5` discards paced capture cycles before recording starts.

Each recording creates a timestamped session directory containing:

- `manifest.json`: camera labels, sources, FPS, and format.
- `metadata.csv`: one row per camera per capture cycle with `monotonic_ns`,
  `system_ns`, `frame_index`, and `skew_ns`.
- One `.avi` file per camera.
- Optional `lidar_udp.csv` and `lidar_udp.bin` files when `--lidar-udp-port` is used.

Summarize a run with:

```bash
python3 analyze_recording.py data/session_YYYYMMDD_HHMMSS
```

Check whether alignment is good enough:

```bash
python3 check_alignment.py data/session_YYYYMMDD_HHMMSS
```

Summarize LiDAR packets:

```bash
python3 analyze_lidar.py data/session_YYYYMMDD_HHMMSS
```

Create an HTML LiDAR timing/rate visualization:

```bash
python3 visualize_lidar_timing.py data/session_YYYYMMDD_HHMMSS
```

Open `lidar_timing.html` from that session in a browser.

Point-cloud visualization requires raw LiDAR packets, not `--lidar-metadata-only`,
plus the LiDAR model/packet decoder.

Export raw LiDAR packets to PCAP for vendor tools:

```bash
python3 export_lidar_pcap.py data/session_YYYYMMDD_HHMMSS --dst-ip 169.254.1.100
```

Open `lidar.pcap` in the LiDAR vendor viewer. Use the model-specific viewer or
SDK, for example Ouster Studio, Hesai PandarView, Velodyne VeloView, or the
vendor's ROS driver.

To list timing outliers above a custom threshold:

```bash
python3 analyze_recording.py data/session_YYYYMMDD_HHMMSS --outlier-ms 5
```

To evaluate an older run after dropping startup cycles:

```bash
python3 analyze_recording.py data/session_YYYYMMDD_HHMMSS --ignore-start-cycles 12
```

`monotonic_ns` is the best timestamp for aligning streams from this process.
`skew_ns` is the measured software timestamp spread across cameras in a cycle.
For true sub-frame synchronization, the cameras need hardware trigger/sync
support; USB webcams cannot guarantee that by software alone.

Optional flags:

```bash
python camera_viewer.py --max-index 12 --width 640 --height 480 --fps 15
```

Controls:

- Press `q` or `Esc` to quit.
- If no cameras appear, make sure your user can access video devices such as `/dev/video0`.

## Troubleshooting

If `python3 -m venv .venv` was interrupted, delete the partial `.venv` folder and create it again:

```bash
rm -rf .venv
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

If `pip install -r requirements.txt` already succeeded with "Defaulting to user installation",
you can run the app without activating a virtualenv:

```bash
python3 camera_viewer.py
```

OpenCV or V4L2 warnings during startup usually mean the system exposed a video node
that is not a normal camera stream. They are not fatal unless no preview window opens.

Many UVC cameras expose two `/dev/video*` nodes. The app filters for primary capture
nodes so six physical cameras should normally show as six previews, not twelve.


<!-- python3 camera_viewer.py \
  --width 320 --height 240 --fps 10 --fourcc MJPG --buffer-size 1 \
  --record-dir data --duration 30 --warmup-seconds 1.5 --no-preview \
  --lidar-bind 169.254.1.100 \
  --lidar-udp-port 47131 --lidar-udp-port 46075 \
  --lidar-writer-queue 2048
After each run, validate with:
python3 analyze_lidar.py data/session_YYYYMMDD_HHMMSS
python3 check_alignment.py data/session_YYYYMMDD_HHMMSS -->
