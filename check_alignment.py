#!/usr/bin/env python3
"""Decide whether a recording session has acceptable camera alignment."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path
from statistics import mean


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check recording alignment quality.")
    parser.add_argument("session", type=Path, help="Recording session directory.")
    parser.add_argument(
        "--expected-cameras",
        type=int,
        default=6,
        help="Expected number of cameras in each capture cycle.",
    )
    parser.add_argument(
        "--max-p95-ms",
        type=float,
        default=2.0,
        help="Fail if p95 cycle skew is above this many milliseconds.",
    )
    parser.add_argument(
        "--max-skew-ms",
        type=float,
        default=5.0,
        help="Fail if any cycle skew is above this many milliseconds.",
    )
    parser.add_argument(
        "--max-outlier-rate",
        type=float,
        default=0.01,
        help="Fail if the fraction of cycles above --max-skew-ms is higher than this.",
    )
    parser.add_argument(
        "--ignore-start-cycles",
        type=int,
        default=0,
        help="Ignore this many initial cycles when checking alignment.",
    )
    return parser.parse_args()


def percentile(values: list[float], percent: float) -> float:
    ordered = sorted(values)
    index = round((len(ordered) - 1) * percent / 100)
    return ordered[index]


def main() -> int:
    args = parse_args()
    metadata_path = args.session / "metadata.csv"
    if not metadata_path.exists():
        print(f"FAIL: missing metadata file: {metadata_path}")
        return 2

    cycle_skews: dict[int, float] = {}
    cycle_camera_counts: dict[int, set[str]] = defaultdict(set)
    failed_frames: list[tuple[int, str]] = []
    frame_counts: dict[str, int] = defaultdict(int)

    with metadata_path.open(newline="", encoding="utf-8") as metadata_file:
        for row in csv.DictReader(metadata_file):
            cycle_index = int(row["cycle_index"])
            if cycle_index < args.ignore_start_cycles:
                continue

            label = row["camera_label"]
            cycle_camera_counts[cycle_index].add(label)
            cycle_skews[cycle_index] = int(row["skew_ns"]) / 1_000_000

            if row["ok"] == "1":
                frame_counts[label] += 1
            else:
                failed_frames.append((cycle_index, label))

    if not cycle_skews:
        print("FAIL: no cycles to check")
        return 2

    skews = list(cycle_skews.values())
    p95_ms = percentile(skews, 95)
    max_ms = max(skews)
    mean_ms = mean(skews)
    outliers = [
        (cycle, skew_ms)
        for cycle, skew_ms in sorted(cycle_skews.items())
        if skew_ms > args.max_skew_ms
    ]
    outlier_rate = len(outliers) / len(cycle_skews)
    incomplete_cycles = [
        cycle
        for cycle, labels in sorted(cycle_camera_counts.items())
        if len(labels) != args.expected_cameras
    ]

    problems: list[str] = []
    if p95_ms > args.max_p95_ms:
        problems.append(
            f"p95 skew {p95_ms:.2f} ms exceeds {args.max_p95_ms:.2f} ms"
        )
    if max_ms > args.max_skew_ms and outlier_rate > args.max_outlier_rate:
        problems.append(
            f"outlier rate {outlier_rate:.2%} exceeds {args.max_outlier_rate:.2%}"
        )
    if failed_frames:
        problems.append(f"{len(failed_frames)} failed frame(s)")
    if incomplete_cycles:
        problems.append(
            f"{len(incomplete_cycles)} cycle(s) do not have {args.expected_cameras} cameras"
        )

    status = "GOOD" if not problems else "FAIL"
    print(f"{status}: alignment check for {args.session}")
    print(f"Cycles checked: {len(cycle_skews)}")
    if args.ignore_start_cycles:
        print(f"Ignored start cycles: {args.ignore_start_cycles}")
    print(
        "Skew ms: "
        f"mean={mean_ms:.2f}, "
        f"p95={p95_ms:.2f}, "
        f"max={max_ms:.2f}"
    )
    print(
        f"Outliers > {args.max_skew_ms:.2f} ms: "
        f"{len(outliers)} ({outlier_rate:.2%})"
    )
    print("Frames:")
    for label in sorted(frame_counts):
        print(f"- {label}: {frame_counts[label]}")

    if problems:
        print("Problems:")
        for problem in problems:
            print(f"- {problem}")
        if outliers:
            print("Largest outliers:")
            for cycle, skew_ms in sorted(outliers, key=lambda item: item[1], reverse=True)[:10]:
                print(f"- cycle {cycle}: {skew_ms:.2f} ms")
        return 1

    print("Decision: alignment is good for software-synchronized USB camera capture.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
