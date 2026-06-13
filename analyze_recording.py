#!/usr/bin/env python3
"""Summarize camera recording metadata."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path
from statistics import mean


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze camera metadata.csv timing.")
    parser.add_argument("session", type=Path, help="Recording session directory.")
    parser.add_argument(
        "--outlier-ms",
        type=float,
        default=10.0,
        help="List cycles with skew greater than this many milliseconds.",
    )
    parser.add_argument(
        "--ignore-start-cycles",
        type=int,
        default=0,
        help="Ignore this many initial cycles when computing the summary.",
    )
    return parser.parse_args()


def percentile(values: list[float], percent: float) -> float:
    if not values:
        return 0.0

    ordered = sorted(values)
    index = round((len(ordered) - 1) * percent / 100)
    return ordered[index]


def main() -> int:
    args = parse_args()
    metadata_path = args.session / "metadata.csv"
    if not metadata_path.exists():
        print(f"Missing metadata file: {metadata_path}")
        return 1

    frame_counts: dict[str, int] = defaultdict(int)
    failed_counts: dict[str, int] = defaultdict(int)
    cycle_skews: dict[int, float] = {}

    with metadata_path.open(newline="", encoding="utf-8") as metadata_file:
        for row in csv.DictReader(metadata_file):
            cycle_index = int(row["cycle_index"])
            if cycle_index < args.ignore_start_cycles:
                continue

            label = row["camera_label"]
            if row["ok"] == "1":
                frame_counts[label] += 1
            else:
                failed_counts[label] += 1

            cycle_skews[cycle_index] = int(row["skew_ns"]) / 1_000_000

    skews = list(cycle_skews.values())
    print(f"Session: {args.session}")
    if args.ignore_start_cycles:
        print(f"Ignored start cycles: {args.ignore_start_cycles}")
    print(f"Cycles: {len(skews)}")
    if not skews:
        print("No cycles to analyze.")
        return 1
    print(
        "Skew ms: "
        f"mean={mean(skews):.2f}, "
        f"p50={percentile(skews, 50):.2f}, "
        f"p95={percentile(skews, 95):.2f}, "
        f"max={max(skews, default=0):.2f}"
    )
    print("Frames:")
    for label in sorted(set(frame_counts) | set(failed_counts)):
        print(
            f"- {label}: ok={frame_counts[label]}, failed={failed_counts[label]}"
        )

    outliers = [
        (cycle, skew_ms)
        for cycle, skew_ms in sorted(cycle_skews.items())
        if skew_ms > args.outlier_ms
    ]
    print(f"Outlier cycles > {args.outlier_ms:.1f} ms: {len(outliers)}")
    for cycle, skew_ms in outliers[:20]:
        print(f"- cycle {cycle}: {skew_ms:.2f} ms")
    if len(outliers) > 20:
        print(f"- ... {len(outliers) - 20} more")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
