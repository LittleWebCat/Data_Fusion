#!/usr/bin/env python3
"""Generate nearest LiDAR cloud images for synchronized camera timestamps."""

from __future__ import annotations

import argparse
import bisect
import csv
import subprocess
from pathlib import Path

from generate_lidar_point_image import (
    iter_lidar_scans,
    latest_dataset,
    render_top_down,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Match every synchronized camera timestamp to the nearest LiDAR scan "
            "and render the unique matched LiDAR cloud images."
        )
    )
    parser.add_argument(
        "dataset",
        nargs="?",
        type=Path,
        help="Dataset folder. Defaults to ~/Downloads/latest_camera_dataset.txt.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Output image directory. Defaults to <dataset>/lidar_matched_images.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        help="Output CSV. Defaults to <dataset>/camera_lidar_image_manifest.csv.",
    )
    parser.add_argument("--size", type=int, default=1000)
    parser.add_argument("--meters", type=float, default=25.0)
    parser.add_argument("--point-radius", type=int, default=1)
    parser.add_argument(
        "--warn-delta-ms",
        type=float,
        default=200.0,
        help="Warn when nearest LiDAR scan is farther than this. Default: 200 ms.",
    )
    return parser.parse_args()


def run_script(script: str, dataset: Path) -> None:
    subprocess.run(
        ["python3", str(Path(__file__).resolve().parent / script), str(dataset)],
        check=True,
    )


def ensure_camera_timestamp_manifest(dataset: Path) -> Path:
    camera_manifest = dataset / "camera_manifest.csv"
    sync_manifest = dataset / "camera_sync_manifest.csv"
    timestamp_manifest = dataset / "camera_sync_timestamp_manifest.csv"

    if not camera_manifest.is_file():
        run_script("make_6cam_manifest.py", dataset)
    if not sync_manifest.is_file():
        run_script("make_6cam_sync_manifest.py", dataset)
    if not timestamp_manifest.is_file():
        run_script("make_6cam_timestamp_manifest.py", dataset)
    return timestamp_manifest


def load_camera_rows(timestamp_manifest: Path) -> list[dict[str, str]]:
    with timestamp_manifest.open(newline="", encoding="utf-8") as manifest_file:
        rows = list(csv.DictReader(manifest_file))
    if not rows:
        raise SystemExit(f"No camera timestamp rows found in {timestamp_manifest}")
    return rows


def nearest_lidar_frame(lidar_times: list[int], camera_time_ns: int) -> int:
    index = bisect.bisect_left(lidar_times, camera_time_ns)
    candidates = []
    if index > 0:
        candidates.append(index - 1)
    if index < len(lidar_times):
        candidates.append(index)
    if not candidates:
        raise SystemExit("No LiDAR frames available for matching.")
    return min(candidates, key=lambda i: abs(lidar_times[i] - camera_time_ns))


def main() -> int:
    args = parse_args()
    dataset = args.dataset or latest_dataset()
    if not dataset.is_dir():
        raise SystemExit(f"Dataset folder does not exist: {dataset}")

    output_dir = args.output_dir or dataset / "lidar_matched_images"
    manifest_path = args.manifest or dataset / "camera_lidar_image_manifest.csv"
    timestamp_manifest = ensure_camera_timestamp_manifest(dataset)
    camera_rows = load_camera_rows(timestamp_manifest)

    print("Reading LiDAR scans...")
    scans = list(iter_lidar_scans(dataset))
    if not scans:
        raise SystemExit("No complete LiDAR scans found.")

    lidar_times = [frame_time_ns for _info, _idx, frame_time_ns, _scan in scans]
    matches: list[tuple[dict[str, str], int, int]] = []
    unique_frame_indices: set[int] = set()
    max_delta_ns = 0

    for row in camera_rows:
        camera_time_ns = int(row["estimated_monotonic_ns"])
        scan_list_index = nearest_lidar_frame(lidar_times, camera_time_ns)
        delta_ns = lidar_times[scan_list_index] - camera_time_ns
        max_delta_ns = max(max_delta_ns, abs(delta_ns))
        unique_frame_indices.add(scan_list_index)
        matches.append((row, scan_list_index, delta_ns))

    print(f"Camera samples: {len(camera_rows)}")
    print(f"Complete LiDAR frames: {len(scans)}")
    print(f"Unique matched LiDAR frames: {len(unique_frame_indices)}")
    print(f"Max nearest-match delta: {max_delta_ns / 1_000_000:.3f} ms")
    if max_delta_ns > int(args.warn_delta_ms * 1_000_000):
        print(
            f"WARN: at least one camera timestamp is more than "
            f"{args.warn_delta_ms:.1f} ms from the nearest LiDAR frame."
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    image_paths: dict[int, Path] = {}
    for scan_list_index in sorted(unique_frame_indices):
        info, lidar_frame_index, _frame_time_ns, scan = scans[scan_list_index]
        image_path = output_dir / f"lidar_frame_{lidar_frame_index:06d}.png"
        if not image_path.is_file():
            render_top_down(
                info,
                scan,
                image_path,
                size=args.size,
                meters=args.meters,
                point_radius=args.point_radius,
            )
        image_paths[scan_list_index] = image_path

    fieldnames = list(camera_rows[0].keys()) + [
        "lidar_frame_index",
        "lidar_frame_monotonic_ns",
        "camera_lidar_delta_ns",
        "camera_lidar_delta_ms",
        "lidar_image_path",
    ]
    with manifest_path.open("w", newline="", encoding="utf-8") as manifest_file:
        writer = csv.DictWriter(manifest_file, fieldnames=fieldnames)
        writer.writeheader()
        for row, scan_list_index, delta_ns in matches:
            _info, lidar_frame_index, lidar_time_ns, _scan = scans[scan_list_index]
            out = dict(row)
            out["lidar_frame_index"] = lidar_frame_index
            out["lidar_frame_monotonic_ns"] = lidar_time_ns
            out["camera_lidar_delta_ns"] = delta_ns
            out["camera_lidar_delta_ms"] = f"{delta_ns / 1_000_000:.6f}"
            out["lidar_image_path"] = str(image_paths[scan_list_index])
            writer.writerow(out)

    print(f"Wrote images: {output_dir}")
    print(f"Wrote manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
