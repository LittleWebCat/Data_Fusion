#!/usr/bin/env python3
"""Show all connected cameras in a single local preview window."""

from __future__ import annotations

import argparse
import csv
import contextlib
import fcntl
import json
import math
import multiprocessing as mp
import os
import queue
import re
import socket
import struct
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


VIDIOC_QUERYCAP = 0x80685600
V4L2_CAP_VIDEO_CAPTURE = 0x00000001
V4L2_CAP_VIDEO_CAPTURE_MPLANE = 0x00001000
V4L2_CAP_DEVICE_CAPS = 0x80000000
DEFAULT_LAYOUT = "4=fL,10=f,8=fR/6=bL,0=b,2=bR"


@dataclass
class Camera:
    label: str
    source: int | str
    capture: cv2.VideoCapture
    frame_index: int = 0


@dataclass(frozen=True)
class CaptureSettings:
    width: int
    height: int
    fps: int
    fourcc: str
    buffer_size: int


@dataclass
class FrameSample:
    camera: Camera
    frame: np.ndarray | None
    frame_index: int
    monotonic_ns: int
    system_ns: int
    ok: bool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Find connected cameras and show their live previews."
    )
    parser.add_argument(
        "--max-index",
        type=int,
        default=10,
        help="Highest numeric camera index to probe, starting at 0.",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=640,
        help="Requested capture width for each camera.",
    )
    parser.add_argument(
        "--height",
        type=int,
        default=480,
        help="Requested capture height for each camera.",
    )
    parser.add_argument(
        "--fps",
        type=int,
        default=15,
        help="Requested frames per second for each camera.",
    )
    parser.add_argument(
        "--fourcc",
        default="MJPG",
        help="Requested camera format, for example MJPG or YUYV.",
    )
    parser.add_argument(
        "--buffer-size",
        type=int,
        default=1,
        help="Requested OpenCV capture buffer size. Lower is better for latency.",
    )
    parser.add_argument(
        "--tile-width",
        type=int,
        default=480,
        help="Display width for each preview tile.",
    )
    parser.add_argument(
        "--tile-height",
        type=int,
        default=360,
        help="Display height for each preview tile.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List detected camera device nodes and exit.",
    )
    parser.add_argument(
        "--probe",
        action="store_true",
        help="Probe detected camera nodes and print negotiated capture properties.",
    )
    parser.add_argument(
        "--layout",
        default=DEFAULT_LAYOUT,
        help=(
            "Camera layout as rows separated by '/', with entries like "
            "'4=fL,10=f,8=fR/6=bL,0=b,2=bR'."
        ),
    )
    parser.add_argument(
        "--record-dir",
        type=Path,
        help="Directory where per-camera video and timestamp metadata will be saved.",
    )
    parser.add_argument(
        "--duration",
        type=float,
        help="Stop automatically after this many seconds.",
    )
    parser.add_argument(
        "--warmup-cycles",
        type=int,
        default=2,
        help="Minimum number of cycles to discard before recording or preview.",
    )
    parser.add_argument(
        "--warmup-seconds",
        type=float,
        default=1.5,
        help="Warm up cameras for this many seconds before recording or preview.",
    )
    parser.add_argument(
        "--sync-warning-ms",
        type=float,
        default=20.0,
        help="Print a warning when software timestamp skew exceeds this many ms.",
    )
    parser.add_argument(
        "--no-preview",
        action="store_true",
        help="Record without opening a preview window.",
    )
    parser.add_argument(
        "--sequential-grab",
        action="store_true",
        help="Grab cameras one at a time instead of using parallel grab threads.",
    )
    parser.add_argument(
        "--lidar-udp-port",
        type=int,
        action="append",
        help="Record LiDAR UDP packets received on this port.",
    )
    parser.add_argument(
        "--lidar-bind",
        default="0.0.0.0",
        help="Local IP address to bind for LiDAR UDP capture.",
    )
    parser.add_argument(
        "--lidar-name",
        default="lidar",
        help="Name prefix for LiDAR output files.",
    )
    parser.add_argument(
        "--lidar-max-packet",
        type=int,
        default=65535,
        help="Maximum LiDAR UDP packet size to receive.",
    )
    parser.add_argument(
        "--lidar-rcvbuf",
        type=int,
        default=4 * 1024 * 1024,
        help="Requested LiDAR UDP receive buffer size in bytes.",
    )
    parser.add_argument(
        "--lidar-metadata-only",
        action="store_true",
        help="Only write LiDAR packet metadata CSV, not raw packet payload binaries.",
    )
    parser.add_argument(
        "--lidar-writer-queue",
        type=int,
        default=1024,
        help="Buffered raw LiDAR packet queue size for the writer process.",
    )
    return parser.parse_args()


def is_linux_capture_device(path: Path) -> bool:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    except OSError:
        return False

    try:
        capability = bytearray(104)
        fcntl.ioctl(fd, VIDIOC_QUERYCAP, capability, True)
    except OSError:
        return False
    finally:
        os.close(fd)

    capabilities = int.from_bytes(capability[84:88], "little")
    device_caps = int.from_bytes(capability[88:92], "little")
    active_caps = device_caps if capabilities & V4L2_CAP_DEVICE_CAPS else capabilities
    capture_caps = V4L2_CAP_VIDEO_CAPTURE | V4L2_CAP_VIDEO_CAPTURE_MPLANE
    return bool(active_caps & capture_caps)


def linux_device_index(path: Path) -> int | None:
    index_path = Path("/sys/class/video4linux") / path.name / "index"
    try:
        return int(index_path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def linux_device_name(path: Path) -> str:
    name_path = Path("/sys/class/video4linux") / path.name / "name"
    try:
        return clean_device_name(name_path.read_text(encoding="utf-8").strip())
    except OSError:
        return path.name


def clean_device_name(name: str) -> str:
    parts = [part.strip() for part in name.split(":")]
    if len(parts) == 2 and parts[0] == parts[1]:
        return parts[0]
    return name


def video_number(path: Path) -> int:
    match = re.search(r"\d+$", path.name)
    return int(match.group()) if match else -1


def source_video_number(source: int | str) -> int | None:
    if isinstance(source, int):
        return source
    return video_number(Path(source))


def linux_video_devices() -> list[str]:
    devices = sorted(Path("/dev").glob("video*"), key=video_number)
    capture_devices = [path for path in devices if is_linux_capture_device(path)]
    primary_devices = [
        path for path in capture_devices if linux_device_index(path) in (None, 0)
    ]
    return [str(path) for path in primary_devices]


def candidate_sources(max_index: int) -> list[int | str]:
    if os.name == "posix":
        devices = linux_video_devices()
        if devices:
            return devices

    return list(range(max_index + 1))


@contextlib.contextmanager
def quiet_opencv_probe() -> None:
    if not hasattr(cv2, "setLogLevel"):
        yield
        return

    previous_level = cv2.getLogLevel() if hasattr(cv2, "getLogLevel") else None
    cv2.setLogLevel(0)
    try:
        yield
    finally:
        if previous_level is not None:
            cv2.setLogLevel(previous_level)


def fingerprint(source: int | str, capture: cv2.VideoCapture) -> str:
    if isinstance(source, str):
        try:
            return str(Path(source).resolve())
        except OSError:
            return source

    backend = int(capture.get(cv2.CAP_PROP_BACKEND))
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    return f"index:{source}:backend:{backend}:size:{width}x{height}"


def format_source(source: int | str) -> str:
    if isinstance(source, str):
        path = Path(source)
        if os.name == "posix" and path.name.startswith("video"):
            return f"{source} ({linux_device_name(path)})"
    return str(source)


def camera_label(source: int | str) -> str:
    if isinstance(source, str):
        path = Path(source)
        if os.name == "posix" and path.name.startswith("video"):
            return f"{path.name}: {linux_device_name(path)}"
    return f"Camera {source}"


def parse_layout(layout: str) -> list[list[tuple[int, str]]]:
    rows: list[list[tuple[int, str]]] = []

    for row_text in layout.split("/"):
        row: list[tuple[int, str]] = []
        for entry_text in row_text.split(","):
            entry = entry_text.strip()
            if not entry:
                continue

            if "=" in entry:
                number_text, label = entry.split("=", 1)
            elif ":" in entry:
                number_text, label = entry.split(":", 1)
            else:
                number_text, label = entry, entry

            match = re.search(r"\d+", number_text)
            if not match:
                continue
            row.append((int(match.group()), label.strip()))

        if row:
            rows.append(row)

    return rows


def apply_layout(cameras: list[Camera], layout: str) -> tuple[list[Camera], int | None]:
    rows = parse_layout(layout)
    if not rows:
        return cameras, None

    cameras_by_number = {
        number: camera
        for camera in cameras
        if (number := source_video_number(camera.source)) is not None
    }

    arranged: list[Camera] = []
    used_numbers: set[int] = set()
    columns = max(len(row) for row in rows)

    for row in rows:
        for number, label in row:
            camera = cameras_by_number.get(number)
            if camera is None:
                continue
            camera.label = f"{label} ({Path(str(camera.source)).name})"
            arranged.append(camera)
            used_numbers.add(number)

    arranged.extend(
        camera
        for camera in cameras
        if source_video_number(camera.source) not in used_numbers
    )
    return arranged, columns if arranged else None


def missing_layout_entries(cameras: list[Camera], layout: str) -> list[str]:
    rows = parse_layout(layout)
    if not rows:
        return []

    discovered_numbers = {
        number
        for camera in cameras
        if (number := source_video_number(camera.source)) is not None
    }

    missing = []
    for row in rows:
        for number, label in row:
            if number not in discovered_numbers:
                missing.append(f"{label} (video{number})")

    return missing


def open_camera(source: int | str, settings: CaptureSettings) -> cv2.VideoCapture | None:
    if isinstance(source, str) and os.name == "posix":
        capture = cv2.VideoCapture(source, cv2.CAP_V4L2)
    else:
        capture = cv2.VideoCapture(source)
    if not capture.isOpened():
        capture.release()
        return None

    capture.set(cv2.CAP_PROP_BUFFERSIZE, settings.buffer_size)
    if settings.fourcc:
        fourcc = settings.fourcc.upper()[:4].ljust(4)
        capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, settings.width)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, settings.height)
    capture.set(cv2.CAP_PROP_FPS, settings.fps)

    ok, _frame = capture.read()
    if not ok:
        capture.release()
        return None

    return capture


def decode_fourcc(value: float) -> str:
    integer = int(value)
    chars = [chr((integer >> 8 * index) & 0xFF) for index in range(4)]
    text = "".join(chars)
    return text if text.strip("\x00") else "unknown"


def probe_camera(source: int | str, settings: CaptureSettings) -> str:
    if isinstance(source, str) and os.name == "posix":
        capture = cv2.VideoCapture(source, cv2.CAP_V4L2)
    else:
        capture = cv2.VideoCapture(source)

    if not capture.isOpened():
        capture.release()
        return f"{format_source(source)}: open failed"

    capture.set(cv2.CAP_PROP_BUFFERSIZE, settings.buffer_size)
    if settings.fourcc:
        fourcc = settings.fourcc.upper()[:4].ljust(4)
        capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, settings.width)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, settings.height)
    capture.set(cv2.CAP_PROP_FPS, settings.fps)

    ok, frame = capture.read()
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = capture.get(cv2.CAP_PROP_FPS)
    negotiated_fourcc = decode_fourcc(capture.get(cv2.CAP_PROP_FOURCC))
    frame_shape = "none" if frame is None else "x".join(map(str, frame.shape[:2]))
    capture.release()

    return (
        f"{format_source(source)}: open ok, read={'ok' if ok else 'failed'}, "
        f"mode={width}x{height}@{fps:.1f}, fourcc={negotiated_fourcc}, "
        f"frame_shape={frame_shape}"
    )


def discover_cameras(max_index: int, settings: CaptureSettings) -> list[Camera]:
    cameras: list[Camera] = []
    seen: set[str] = set()

    with quiet_opencv_probe():
        for source in candidate_sources(max_index):
            capture = open_camera(source, settings)
            if capture is None:
                continue

            key = fingerprint(source, capture)
            if key in seen:
                capture.release()
                continue

            seen.add(key)
            cameras.append(
                Camera(label=camera_label(source), source=source, capture=capture)
            )

    return cameras


def sanitize_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")
    return cleaned or "camera"


def lidar_binary_writer(binary_path: str, write_queue: mp.Queue) -> None:
    with open(binary_path, "wb") as binary_file:
        while True:
            item = write_queue.get()
            if item is None:
                break

            monotonic_ns, system_ns, payload = item
            binary_file.write(
                struct.pack("<QQI", monotonic_ns, system_ns, len(payload))
            )
            binary_file.write(payload)


class Recorder:
    def __init__(self, root: Path, fps: int, fourcc: str, cameras: list[Camera]) -> None:
        session_name = time.strftime("session_%Y%m%d_%H%M%S")
        self.session_dir = root / session_name
        self.session_dir.mkdir(parents=True, exist_ok=False)
        self.fps = fps
        self.fourcc = cv2.VideoWriter_fourcc(*fourcc.upper()[:4].ljust(4))
        self.writers: dict[str, cv2.VideoWriter] = {}
        self.video_paths: dict[str, Path] = {}
        self.metadata_file = (self.session_dir / "metadata.csv").open(
            "w", newline="", encoding="utf-8"
        )
        self.metadata = csv.DictWriter(
            self.metadata_file,
            fieldnames=[
                "cycle_index",
                "camera_label",
                "source",
                "frame_index",
                "monotonic_ns",
                "system_ns",
                "skew_ns",
                "ok",
                "width",
                "height",
                "video_file",
            ],
        )
        self.metadata.writeheader()

        manifest = {
            "created_system_ns": time.time_ns(),
            "created_monotonic_ns": time.monotonic_ns(),
            "fps": fps,
            "fourcc": fourcc,
            "cameras": [
                {"label": camera.label, "source": str(camera.source)}
                for camera in cameras
            ],
        }
        (self.session_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )

    def _writer_for(self, sample: FrameSample) -> tuple[cv2.VideoWriter, Path]:
        key = sample.camera.label
        writer = self.writers.get(key)
        if writer is not None:
            return writer, self.video_paths[key]

        assert sample.frame is not None
        height, width = sample.frame.shape[:2]
        video_path = self.session_dir / f"{sanitize_filename(key)}.avi"
        writer = cv2.VideoWriter(str(video_path), self.fourcc, self.fps, (width, height))
        if not writer.isOpened():
            raise RuntimeError(f"Could not open video writer for {video_path}")

        self.writers[key] = writer
        self.video_paths[key] = video_path
        return writer, video_path

    def write_cycle(
        self, cycle_index: int, samples: list[FrameSample], skew_ns: int
    ) -> None:
        for sample in samples:
            video_file = ""
            width = 0
            height = 0

            if sample.ok and sample.frame is not None:
                writer, video_path = self._writer_for(sample)
                writer.write(sample.frame)
                height, width = sample.frame.shape[:2]
                video_file = video_path.name

            self.metadata.writerow(
                {
                    "cycle_index": cycle_index,
                    "camera_label": sample.camera.label,
                    "source": str(sample.camera.source),
                    "frame_index": sample.frame_index,
                    "monotonic_ns": sample.monotonic_ns,
                    "system_ns": sample.system_ns,
                    "skew_ns": skew_ns,
                    "ok": int(sample.ok),
                    "width": width,
                    "height": height,
                    "video_file": video_file,
                }
            )

        self.metadata_file.flush()

    def close(self) -> None:
        for writer in self.writers.values():
            writer.release()
        self.metadata_file.close()


class LidarUdpRecorder:
    def __init__(
        self,
        session_dir: Path,
        bind_ip: str,
        port: int,
        name: str,
        max_packet_size: int,
        receive_buffer_size: int,
        metadata_only: bool,
        writer_queue_size: int,
    ) -> None:
        self.session_dir = session_dir
        self.bind_ip = bind_ip
        self.port = port
        self.name = sanitize_filename(name)
        self.max_packet_size = max_packet_size
        self.metadata_only = metadata_only
        self.stop_event = threading.Event()
        self.packet_count = 0
        self.byte_count = 0
        self.raw_dropped_count = 0
        self.raw_offset = 0
        self.binary_path = session_dir / f"{self.name}_udp.bin"
        self.write_queue = None
        self.writer_process = None
        if not metadata_only:
            context = mp.get_context("spawn")
            self.write_queue = context.Queue(maxsize=writer_queue_size)
            self.writer_process = context.Process(
                target=lidar_binary_writer,
                args=(str(self.binary_path), self.write_queue),
                name=f"{self.name}-binary-writer",
            )
        self.metadata_file = (session_dir / f"{self.name}_udp.csv").open(
            "w", newline="", encoding="utf-8"
        )
        self.metadata = csv.DictWriter(
            self.metadata_file,
            fieldnames=[
                "packet_index",
                "monotonic_ns",
                "system_ns",
                "source_ip",
                "source_port",
                "size",
                "binary_offset",
                "raw_dropped",
            ],
        )
        self.metadata.writeheader()
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, receive_buffer_size)
        self.socket.settimeout(0.25)
        self.socket.bind((bind_ip, port))
        self.thread = threading.Thread(target=self._run, name=f"{self.name}-udp")

    def start(self) -> None:
        if self.writer_process is not None:
            self.writer_process.start()
        self.thread.start()

    def _run(self) -> None:
        while not self.stop_event.is_set():
            try:
                payload, address = self.socket.recvfrom(self.max_packet_size)
            except socket.timeout:
                continue
            except OSError:
                break

            monotonic_ns = time.monotonic_ns()
            system_ns = time.time_ns()
            offset = -1
            raw_dropped = 0
            if self.write_queue is not None:
                offset = self.raw_offset
                try:
                    self.write_queue.put_nowait((monotonic_ns, system_ns, payload))
                    self.raw_offset += 20 + len(payload)
                except queue.Full:
                    offset = -1
                    raw_dropped = 1
                    self.raw_dropped_count += 1
            self.metadata.writerow(
                {
                    "packet_index": self.packet_count,
                    "monotonic_ns": monotonic_ns,
                    "system_ns": system_ns,
                    "source_ip": address[0],
                    "source_port": address[1],
                    "size": len(payload),
                    "binary_offset": offset,
                    "raw_dropped": raw_dropped,
                }
            )
            self.packet_count += 1
            self.byte_count += len(payload)

    def close(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=1.0)
        self.socket.close()
        if self.write_queue is not None:
            self.write_queue.put(None)
        if self.writer_process is not None:
            self.writer_process.join(timeout=10.0)
            if self.writer_process.is_alive():
                self.writer_process.terminate()
                self.writer_process.join(timeout=2.0)
        self.metadata_file.flush()
        self.metadata_file.close()


def grab_camera(camera: Camera) -> tuple[Camera, bool, int, int]:
    ok = camera.capture.grab()
    monotonic_ns = time.monotonic_ns()
    system_ns = time.time_ns()
    return camera, ok, monotonic_ns, system_ns


def capture_cycle(
    cameras: list[Camera], executor: ThreadPoolExecutor | None = None
) -> tuple[list[FrameSample], int]:
    if executor is None:
        grabbed = [grab_camera(camera) for camera in cameras]
    else:
        grabbed = list(executor.map(grab_camera, cameras))

    samples: list[FrameSample] = []
    for camera, grabbed_ok, monotonic_ns, system_ns in grabbed:
        frame = None
        ok = False
        if grabbed_ok:
            ok, frame = camera.capture.retrieve()
            ok = ok and frame is not None

        if ok:
            camera.frame_index += 1

        samples.append(
            FrameSample(
                camera=camera,
                frame=frame,
                frame_index=camera.frame_index,
                monotonic_ns=monotonic_ns,
                system_ns=system_ns,
                ok=ok,
            )
        )

    timestamps = [sample.monotonic_ns for sample in samples if sample.ok]
    skew_ns = max(timestamps) - min(timestamps) if len(timestamps) > 1 else 0
    return samples, skew_ns


def frame_or_placeholder(
    sample: FrameSample, tile_size: tuple[int, int], skew_ns: int
) -> np.ndarray:
    camera = sample.camera
    tile_width, tile_height = tile_size

    if not sample.ok or sample.frame is None:
        frame = np.zeros((tile_height, tile_width, 3), dtype=np.uint8)
        cv2.putText(
            frame,
            "No frame",
            (24, tile_height // 2),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.9,
            (180, 180, 180),
            2,
            cv2.LINE_AA,
        )
    else:
        frame = cv2.resize(sample.frame, tile_size, interpolation=cv2.INTER_AREA)

    cv2.rectangle(frame, (0, 0), (tile_width, 34), (0, 0, 0), -1)
    cv2.putText(
        frame,
        f"{camera.label}  skew {skew_ns / 1_000_000:.1f} ms",
        (12, 24),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    return frame


def make_grid(
    frames: list[np.ndarray], tile_size: tuple[int, int], columns: int | None = None
) -> np.ndarray:
    tile_width, tile_height = tile_size
    columns = columns or math.ceil(math.sqrt(len(frames)))
    rows = math.ceil(len(frames) / columns)
    blank = np.zeros((tile_height, tile_width, 3), dtype=np.uint8)

    padded = frames + [blank] * (rows * columns - len(frames))
    row_images = [
        np.hstack(padded[row * columns : (row + 1) * columns]) for row in range(rows)
    ]
    return np.vstack(row_images)


def show_cameras(
    cameras: list[Camera],
    tile_width: int,
    tile_height: int,
    columns: int | None = None,
    recorder: Recorder | None = None,
    duration: float | None = None,
    sync_warning_ms: float = 20.0,
    preview: bool = True,
    target_fps: int = 15,
    parallel_grab: bool = True,
    warmup_cycles: int = 0,
    warmup_seconds: float = 0.0,
) -> None:
    tile_size = (tile_width, tile_height)
    window_name = "Connected Cameras"
    if preview:
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

    cycle_index = 0
    start_time = time.monotonic()
    next_frame_time = start_time
    last_sync_warning_time = 0.0
    frame_period = 1.0 / target_fps if target_fps > 0 else 0.0

    executor_context = (
        ThreadPoolExecutor(max_workers=len(cameras)) if parallel_grab else contextlib.nullcontext()
    )

    with executor_context as executor:
        paced_warmup_cycles = math.ceil(max(0.0, warmup_seconds) * target_fps)
        total_warmup_cycles = max(0, warmup_cycles, paced_warmup_cycles)
        warmup_frame_period = frame_period if frame_period > 0 else 0.0
        warmup_next_frame_time = time.monotonic()

        for _ in range(total_warmup_cycles):
            capture_cycle(cameras, executor)
            warmup_next_frame_time += warmup_frame_period
            sleep_for = warmup_next_frame_time - time.monotonic()
            if sleep_for > 0:
                time.sleep(sleep_for)

        for camera in cameras:
            camera.frame_index = 0

        start_time = time.monotonic()
        next_frame_time = start_time

        while True:
            samples, skew_ns = capture_cycle(cameras, executor)
            skew_ms = skew_ns / 1_000_000
            now = time.monotonic()

            if recorder is not None:
                recorder.write_cycle(cycle_index, samples, skew_ns)

            if skew_ms > sync_warning_ms and now - last_sync_warning_time >= 1.0:
                print(f"Warning: camera timestamp skew is {skew_ms:.1f} ms")
                last_sync_warning_time = now

            if preview:
                frames = [
                    frame_or_placeholder(sample, tile_size, skew_ns) for sample in samples
                ]
                cv2.imshow(window_name, make_grid(frames, tile_size, columns))

                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27):
                    break

            cycle_index += 1

            if duration is not None and now - start_time >= duration:
                break

            next_frame_time += frame_period
            sleep_for = next_frame_time - time.monotonic()
            if sleep_for > 0:
                time.sleep(sleep_for)


def main() -> int:
    args = parse_args()
    settings = CaptureSettings(
        width=args.width,
        height=args.height,
        fps=args.fps,
        fourcc=args.fourcc,
        buffer_size=args.buffer_size,
    )

    if args.list:
        sources = candidate_sources(args.max_index)
        if not sources:
            print("No camera device nodes were detected.")
            return 1

        print("Detected camera candidates:")
        for source in sources:
            print(f"- {format_source(source)}")
        return 0

    if args.probe:
        sources = candidate_sources(args.max_index)
        if not sources:
            print("No camera device nodes were detected.")
            return 1

        print("Camera probe:")
        with quiet_opencv_probe():
            for source in sources:
                print(f"- {probe_camera(source, settings)}")
        return 0

    cameras = discover_cameras(args.max_index, settings)
    missing = missing_layout_entries(cameras, args.layout)
    cameras, columns = apply_layout(cameras, args.layout)

    if not cameras:
        print("No connected cameras were found.")
        print("Try increasing --max-index or checking OS camera permissions.")
        return 1

    if args.lidar_udp_port is not None and args.record_dir is None:
        print("--lidar-udp-port requires --record-dir so LiDAR data has a session folder.")
        return 1

    print(f"Found {len(cameras)} camera(s):")
    for camera in cameras:
        print(f"- {camera.label}")
    if missing:
        print("Missing expected layout camera(s):")
        for label in missing:
            print(f"- {label}")
        print("Try lower resolution/FPS, or confirm the device is not already in use.")

    recorder = None
    lidar_recorders: list[LidarUdpRecorder] = []
    if args.record_dir is not None:
        recorder = Recorder(args.record_dir, args.fps, args.fourcc, cameras)
        print(f"Recording to {recorder.session_dir}")
        if args.lidar_udp_port is not None:
            for port in args.lidar_udp_port:
                stream_name = (
                    args.lidar_name
                    if len(args.lidar_udp_port) == 1
                    else f"{args.lidar_name}_{port}"
                )
                lidar_recorder = LidarUdpRecorder(
                    session_dir=recorder.session_dir,
                    bind_ip=args.lidar_bind,
                    port=port,
                    name=stream_name,
                    max_packet_size=args.lidar_max_packet,
                    receive_buffer_size=args.lidar_rcvbuf,
                    metadata_only=args.lidar_metadata_only,
                    writer_queue_size=args.lidar_writer_queue,
                )
                lidar_recorder.start()
                lidar_recorders.append(lidar_recorder)
                print(
                    f"Recording LiDAR UDP on {args.lidar_bind}:{port} "
                    f"to {recorder.session_dir} as {stream_name}"
                )

    try:
        show_cameras(
            cameras,
            args.tile_width,
            args.tile_height,
            columns,
            recorder=recorder,
            duration=args.duration,
            sync_warning_ms=args.sync_warning_ms,
            preview=not args.no_preview,
            target_fps=args.fps,
            parallel_grab=not args.sequential_grab,
            warmup_cycles=args.warmup_cycles,
            warmup_seconds=args.warmup_seconds,
        )
    finally:
        for lidar_recorder in lidar_recorders:
            lidar_recorder.close()
            print(
                f"LiDAR {lidar_recorder.name} packets recorded: {lidar_recorder.packet_count} "
                f"({lidar_recorder.byte_count} bytes, "
                f"raw_dropped={lidar_recorder.raw_dropped_count})"
            )
        if recorder is not None:
            recorder.close()
        for camera in cameras:
            camera.capture.release()
        cv2.destroyAllWindows()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
