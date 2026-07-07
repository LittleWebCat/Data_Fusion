#!/usr/bin/env python3
"""Render a top-down point image from the kit's recorded Ouster LiDAR packets."""

from __future__ import annotations

import argparse
import struct
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from ouster.sdk import core


RECORD_HEADER = struct.Struct("<QQI")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a PNG point image from a recorded Ouster LiDAR dataset."
    )
    parser.add_argument(
        "dataset",
        nargs="?",
        type=Path,
        help="Dataset folder. Defaults to ~/Downloads/latest_camera_dataset.txt.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output PNG. Defaults to <dataset>/lidar_point_image.png.",
    )
    parser.add_argument(
        "--frame",
        type=int,
        default=5,
        help="Zero-based LiDAR frame to render after packet batching. Default: 5.",
    )
    parser.add_argument(
        "--size",
        type=int,
        default=1400,
        help="Output image width/height in pixels. Default: 1400.",
    )
    parser.add_argument(
        "--meters",
        type=float,
        default=25.0,
        help="Half-width of top-down view in meters. Default: 25.",
    )
    parser.add_argument(
        "--point-radius",
        type=int,
        default=1,
        help="Radius of rendered points in pixels. Default: 1.",
    )
    return parser.parse_args()


def latest_dataset() -> Path:
    latest_path = Path.home() / "Downloads" / "latest_camera_dataset.txt"
    if not latest_path.is_file():
        raise SystemExit(f"Missing latest dataset pointer: {latest_path}")
    return Path(latest_path.read_text(encoding="utf-8").strip())


def iter_lidar_payloads(binary_path: Path):
    with binary_path.open("rb") as binary_file:
        while True:
            header = binary_file.read(RECORD_HEADER.size)
            if not header:
                break
            if len(header) != RECORD_HEADER.size:
                raise ValueError(f"Truncated packet header in {binary_path}")
            monotonic_ns, _system_time_ns, payload_size = RECORD_HEADER.unpack(header)
            payload = binary_file.read(payload_size)
            if len(payload) != payload_size:
                raise ValueError(f"Truncated packet payload in {binary_path}")
            yield monotonic_ns, payload


def read_scan(dataset: Path, frame_index: int) -> tuple[core.SensorInfo, core.LidarScan]:
    lidar_dir = dataset / "lidar"
    metadata_path = lidar_dir / "ouster_metadata.json"
    binary_path = lidar_dir / "lidar_7502_udp.bin"

    if not metadata_path.is_file():
        raise SystemExit(f"Missing Ouster metadata: {metadata_path}")
    if not binary_path.is_file():
        raise SystemExit(f"Missing raw LiDAR binary: {binary_path}")

    info = core.SensorInfo(metadata_path.read_text(encoding="utf-8"))
    packet_format = core.PacketFormat(info)
    batcher = core.ScanBatcher(info)
    scan = core.LidarScan(
        info.format.pixels_per_column,
        info.format.columns_per_frame,
        info.format.udp_profile_lidar,
    )

    completed_index = -1
    for monotonic_ns, payload in iter_lidar_payloads(binary_path):
        if len(payload) != packet_format.lidar_packet_size:
            continue

        packet = core.LidarPacket(packet_format.lidar_packet_size)
        packet.buf[:] = np.frombuffer(payload, dtype=np.uint8)
        packet.host_timestamp = monotonic_ns
        packet.format = packet_format

        if batcher(packet, scan):
            completed_index += 1
            if completed_index >= frame_index:
                return info, scan
            scan = core.LidarScan(
                info.format.pixels_per_column,
                info.format.columns_per_frame,
                info.format.udp_profile_lidar,
            )

    raise SystemExit(
        f"Only found {completed_index + 1} complete LiDAR frames; "
        f"cannot render frame {frame_index}."
    )


def iter_lidar_scans(dataset: Path):
    lidar_dir = dataset / "lidar"
    metadata_path = lidar_dir / "ouster_metadata.json"
    binary_path = lidar_dir / "lidar_7502_udp.bin"

    if not metadata_path.is_file():
        raise SystemExit(f"Missing Ouster metadata: {metadata_path}")
    if not binary_path.is_file():
        raise SystemExit(f"Missing raw LiDAR binary: {binary_path}")

    info = core.SensorInfo(metadata_path.read_text(encoding="utf-8"))
    packet_format = core.PacketFormat(info)
    batcher = core.ScanBatcher(info)
    scan = core.LidarScan(
        info.format.pixels_per_column,
        info.format.columns_per_frame,
        info.format.udp_profile_lidar,
    )

    frame_index = -1
    packet_timestamps: list[int] = []
    for monotonic_ns, payload in iter_lidar_payloads(binary_path):
        if len(payload) != packet_format.lidar_packet_size:
            continue

        packet = core.LidarPacket(packet_format.lidar_packet_size)
        packet.buf[:] = np.frombuffer(payload, dtype=np.uint8)
        packet.host_timestamp = monotonic_ns
        packet.format = packet_format
        packet_timestamps.append(monotonic_ns)

        if batcher(packet, scan):
            frame_index += 1
            frame_monotonic_ns = int(np.median(packet_timestamps))
            yield info, frame_index, frame_monotonic_ns, scan
            packet_timestamps = []
            scan = core.LidarScan(
                info.format.pixels_per_column,
                info.format.columns_per_frame,
                info.format.udp_profile_lidar,
            )


def colorize_by_height(z_values: np.ndarray) -> np.ndarray:
    z_low, z_high = np.percentile(z_values, [2, 98])
    if z_high <= z_low:
        z_high = z_low + 1.0
    t = np.clip((z_values - z_low) / (z_high - z_low), 0.0, 1.0)

    colors = np.empty((len(z_values), 3), dtype=np.uint8)
    colors[:, 0] = (40 + 215 * t).astype(np.uint8)
    colors[:, 1] = (190 - 90 * t).astype(np.uint8)
    colors[:, 2] = (255 - 220 * t).astype(np.uint8)
    return colors


def render_top_down(
    info: core.SensorInfo,
    scan: core.LidarScan,
    output_path: Path,
    size: int,
    meters: float,
    point_radius: int,
) -> None:
    ranges = scan.field(core.ChanField.RANGE)
    xyz = core.XYZLut(info)(ranges)
    valid = ranges > 0
    points = xyz[valid]

    if points.size == 0:
        raise SystemExit("No valid range points found in selected LiDAR frame.")

    x = points[:, 0]
    y = points[:, 1]
    z = points[:, 2]
    in_view = (np.abs(x) <= meters) & (np.abs(y) <= meters)
    x = x[in_view]
    y = y[in_view]
    z = z[in_view]
    if len(x) == 0:
        raise SystemExit(f"No points inside +/-{meters} meters view.")

    px = ((y + meters) / (2 * meters) * (size - 1)).astype(np.int32)
    py = ((meters - x) / (2 * meters) * (size - 1)).astype(np.int32)
    colors = colorize_by_height(z)

    image = Image.new("RGB", (size, size), (8, 12, 16))
    draw = ImageDraw.Draw(image)
    radius = max(0, point_radius)
    for x_px, y_px, color in zip(px, py, colors, strict=False):
        fill = tuple(int(c) for c in color)
        if radius <= 0:
            image.putpixel((int(x_px), int(y_px)), fill)
        else:
            draw.ellipse(
                (
                    int(x_px) - radius,
                    int(y_px) - radius,
                    int(x_px) + radius,
                    int(y_px) + radius,
                ),
                fill=fill,
            )

    draw.line((size // 2, 0, size // 2, size), fill=(42, 52, 62))
    draw.line((0, size // 2, size, size // 2), fill=(42, 52, 62))
    draw.ellipse(
        (size // 2 - 5, size // 2 - 5, size // 2 + 5, size // 2 + 5),
        fill=(255, 255, 255),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)


def main() -> int:
    args = parse_args()
    dataset = args.dataset or latest_dataset()
    if not dataset.is_dir():
        raise SystemExit(f"Dataset folder does not exist: {dataset}")

    output = args.output or dataset / "lidar_point_image.png"
    info, scan = read_scan(dataset, args.frame)
    render_top_down(info, scan, output, args.size, args.meters, args.point_radius)
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
