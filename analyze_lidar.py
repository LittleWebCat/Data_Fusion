#!/usr/bin/env python3
"""Summarize timestamped LiDAR UDP capture files."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from statistics import mean


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze LiDAR UDP metadata.")
    parser.add_argument("session", type=Path, help="Recording session directory.")
    parser.add_argument(
        "--name",
        help="LiDAR file prefix, matching --lidar-name from camera_viewer.py.",
    )
    return parser.parse_args()


def read_camera_range(session: Path) -> tuple[int, int] | None:
    metadata_path = session / "metadata.csv"
    if not metadata_path.exists():
        return None

    timestamps = []
    with metadata_path.open(newline="", encoding="utf-8") as metadata_file:
        for row in csv.DictReader(metadata_file):
            if row["ok"] == "1":
                timestamps.append(int(row["monotonic_ns"]))

    if not timestamps:
        return None
    return min(timestamps), max(timestamps)


def analyze_stream(session: Path, metadata_path: Path) -> bool:
    prefix = metadata_path.name.removesuffix("_udp.csv")
    binary_path = session / f"{prefix}_udp.bin"
    if not metadata_path.exists():
        print(f"Missing LiDAR metadata file: {metadata_path}")
        return False

    timestamps = []
    sizes = []
    raw_dropped = 0
    sources: set[tuple[str, str]] = set()

    with metadata_path.open(newline="", encoding="utf-8") as metadata_file:
        for row in csv.DictReader(metadata_file):
            timestamps.append(int(row["monotonic_ns"]))
            sizes.append(int(row["size"]))
            raw_dropped += int(row.get("raw_dropped", "0") or "0")
            sources.add((row["source_ip"], row["source_port"]))

    print(f"Session: {session}")
    print(f"LiDAR metadata: {metadata_path.name}")
    if binary_path.exists():
        print(f"LiDAR binary: {binary_path.name}")
    else:
        print("LiDAR binary: not present")
    print(f"Packets: {len(timestamps)}")

    if not timestamps:
        print("No LiDAR packets recorded.")
        return False

    duration_s = (max(timestamps) - min(timestamps)) / 1_000_000_000
    packet_rate = len(timestamps) / duration_s if duration_s > 0 else 0.0
    total_bytes = sum(sizes)
    print(f"Duration: {duration_s:.3f} s")
    print(f"Packet rate: {packet_rate:.1f} packets/s")
    print(f"Bytes: {total_bytes}")
    print(f"Raw payload drops: {raw_dropped}")
    print(f"Packet size: mean={mean(sizes):.1f}, min={min(sizes)}, max={max(sizes)}")
    print("Sources:")
    for ip, port in sorted(sources):
        print(f"- {ip}:{port}")

    camera_range = read_camera_range(session)
    if camera_range is not None:
        camera_start, camera_end = camera_range
        lidar_start, lidar_end = min(timestamps), max(timestamps)
        overlap_start = max(camera_start, lidar_start)
        overlap_end = min(camera_end, lidar_end)
        overlap_s = max(0, overlap_end - overlap_start) / 1_000_000_000
        print(f"Camera/LiDAR overlap: {overlap_s:.3f} s")
        if overlap_s <= 0:
            print("Warning: LiDAR timestamps do not overlap camera timestamps.")

    return True


def main() -> int:
    args = parse_args()
    if args.name:
        metadata_paths = [args.session / f"{args.name}_udp.csv"]
    else:
        metadata_paths = sorted(args.session.glob("*_udp.csv"))

    if not metadata_paths:
        print(f"No LiDAR metadata files found in {args.session}")
        return 1

    ok = True
    for index, metadata_path in enumerate(metadata_paths):
        if index:
            print()
        ok = analyze_stream(args.session, metadata_path) and ok

    if not ok:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
