#!/usr/bin/env python3
"""Create an HTML timing visualization for LiDAR UDP metadata."""

from __future__ import annotations

import argparse
import csv
import html
import json
from collections import defaultdict
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Visualize LiDAR packet timing.")
    parser.add_argument("session", type=Path, help="Recording session directory.")
    parser.add_argument(
        "--bin-ms",
        type=float,
        default=100.0,
        help="Histogram bin size in milliseconds.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output HTML path. Defaults to lidar_timing.html in the session.",
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


def load_stream(metadata_path: Path, start_ns: int, bin_ns: int) -> dict:
    bins: dict[int, int] = defaultdict(int)
    sizes: list[int] = []
    timestamps: list[int] = []
    sources: set[str] = set()

    with metadata_path.open(newline="", encoding="utf-8") as metadata_file:
        for row in csv.DictReader(metadata_file):
            timestamp = int(row["monotonic_ns"])
            size = int(row["size"])
            bin_index = (timestamp - start_ns) // bin_ns
            bins[int(bin_index)] += 1
            sizes.append(size)
            timestamps.append(timestamp)
            sources.add(f"{row['source_ip']}:{row['source_port']}")

    if not timestamps:
        return {
            "name": metadata_path.name.removesuffix("_udp.csv"),
            "points": [],
            "packet_count": 0,
            "byte_count": 0,
            "sources": [],
        }

    return {
        "name": metadata_path.name.removesuffix("_udp.csv"),
        "points": [
            {"t": index * bin_ns / 1_000_000_000, "packets": count}
            for index, count in sorted(bins.items())
        ],
        "packet_count": len(timestamps),
        "byte_count": sum(sizes),
        "duration_s": (max(timestamps) - min(timestamps)) / 1_000_000_000,
        "mean_packet_size": sum(sizes) / len(sizes),
        "sources": sorted(sources),
    }


def build_html(session: Path, streams: list[dict], camera_range: tuple[int, int] | None) -> str:
    payload = {
        "session": str(session),
        "streams": streams,
        "cameraDuration": (
            (camera_range[1] - camera_range[0]) / 1_000_000_000
            if camera_range is not None
            else None
        ),
    }
    data_json = json.dumps(payload)
    title = html.escape(f"LiDAR Timing - {session.name}")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <style>
    body {{
      margin: 0;
      font-family: Arial, sans-serif;
      background: #f6f7f9;
      color: #1f2933;
    }}
    main {{
      max-width: 1100px;
      margin: 0 auto;
      padding: 24px;
    }}
    h1 {{
      font-size: 24px;
      margin: 0 0 8px;
    }}
    .summary {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 12px;
      margin: 18px 0;
    }}
    .card {{
      background: white;
      border: 1px solid #dde3ea;
      border-radius: 8px;
      padding: 14px;
    }}
    .label {{
      color: #64748b;
      font-size: 12px;
      text-transform: uppercase;
    }}
    .value {{
      font-size: 22px;
      margin-top: 6px;
      font-weight: 700;
    }}
    canvas {{
      display: block;
      width: 100%;
      height: 420px;
      background: white;
      border: 1px solid #dde3ea;
      border-radius: 8px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: white;
      border: 1px solid #dde3ea;
      border-radius: 8px;
      overflow: hidden;
      margin-top: 18px;
    }}
    th, td {{
      text-align: left;
      padding: 10px 12px;
      border-bottom: 1px solid #edf1f5;
    }}
    th {{
      background: #eef3f8;
    }}
  </style>
</head>
<body>
<main>
  <h1>LiDAR Timing</h1>
  <div id="session"></div>
  <div class="summary" id="summary"></div>
  <canvas id="chart" width="1100" height="420"></canvas>
  <table>
    <thead>
      <tr>
        <th>Stream</th>
        <th>Packets</th>
        <th>Rate</th>
        <th>Bytes</th>
        <th>Mean Size</th>
        <th>Source</th>
      </tr>
    </thead>
    <tbody id="rows"></tbody>
  </table>
</main>
<script>
const data = {data_json};
const colors = ["#2563eb", "#dc2626", "#059669", "#7c3aed"];
document.getElementById("session").textContent = data.session;
const summary = document.getElementById("summary");
const totalPackets = data.streams.reduce((sum, stream) => sum + stream.packet_count, 0);
const totalBytes = data.streams.reduce((sum, stream) => sum + stream.byte_count, 0);
summary.innerHTML = `
  <div class="card"><div class="label">Streams</div><div class="value">${{data.streams.length}}</div></div>
  <div class="card"><div class="label">Packets</div><div class="value">${{totalPackets.toLocaleString()}}</div></div>
  <div class="card"><div class="label">Bytes</div><div class="value">${{totalBytes.toLocaleString()}}</div></div>
  <div class="card"><div class="label">Camera Duration</div><div class="value">${{data.cameraDuration?.toFixed(3) ?? "n/a"}} s</div></div>
`;
const rows = document.getElementById("rows");
rows.innerHTML = data.streams.map((stream) => {{
  const rate = stream.duration_s ? stream.packet_count / stream.duration_s : 0;
  return `<tr>
    <td>${{stream.name}}</td>
    <td>${{stream.packet_count.toLocaleString()}}</td>
    <td>${{rate.toFixed(1)}} /s</td>
    <td>${{stream.byte_count.toLocaleString()}}</td>
    <td>${{stream.mean_packet_size?.toFixed(1) ?? "0"}}</td>
    <td>${{stream.sources.join(", ")}}</td>
  </tr>`;
}}).join("");
const canvas = document.getElementById("chart");
const ctx = canvas.getContext("2d");
const padding = {{ left: 60, right: 20, top: 30, bottom: 50 }};
const width = canvas.width - padding.left - padding.right;
const height = canvas.height - padding.top - padding.bottom;
const maxT = Math.max(1, ...data.streams.flatMap(s => s.points.map(p => p.t)));
const maxPackets = Math.max(1, ...data.streams.flatMap(s => s.points.map(p => p.packets)));
function x(t) {{ return padding.left + (t / maxT) * width; }}
function y(v) {{ return padding.top + height - (v / maxPackets) * height; }}
ctx.clearRect(0, 0, canvas.width, canvas.height);
ctx.strokeStyle = "#d8e0e8";
ctx.lineWidth = 1;
for (let i = 0; i <= 5; i++) {{
  const yy = padding.top + i * height / 5;
  ctx.beginPath();
  ctx.moveTo(padding.left, yy);
  ctx.lineTo(padding.left + width, yy);
  ctx.stroke();
}}
ctx.fillStyle = "#475569";
ctx.font = "13px Arial";
ctx.fillText("Packets per bin", padding.left, 18);
ctx.fillText("Time (s)", padding.left + width - 55, canvas.height - 14);
data.streams.forEach((stream, streamIndex) => {{
  ctx.strokeStyle = colors[streamIndex % colors.length];
  ctx.lineWidth = 2;
  ctx.beginPath();
  stream.points.forEach((point, index) => {{
    const xx = x(point.t);
    const yy = y(point.packets);
    if (index === 0) ctx.moveTo(xx, yy);
    else ctx.lineTo(xx, yy);
  }});
  ctx.stroke();
  ctx.fillStyle = colors[streamIndex % colors.length];
  ctx.fillText(stream.name, padding.left + 10, padding.top + 18 + streamIndex * 18);
}});
</script>
</body>
</html>
"""


def main() -> int:
    args = parse_args()
    metadata_paths = sorted(args.session.glob("*_udp.csv"))
    if not metadata_paths:
        print(f"No LiDAR metadata files found in {args.session}")
        return 1

    camera_range = read_camera_range(args.session)
    start_candidates = []
    if camera_range is not None:
        start_candidates.append(camera_range[0])
    for metadata_path in metadata_paths:
        with metadata_path.open(newline="", encoding="utf-8") as metadata_file:
            for row in csv.DictReader(metadata_file):
                start_candidates.append(int(row["monotonic_ns"]))
                break

    start_ns = min(start_candidates)
    bin_ns = int(args.bin_ms * 1_000_000)
    streams = [load_stream(path, start_ns, bin_ns) for path in metadata_paths]
    output_path = args.output or args.session / "lidar_timing.html"
    output_path.write_text(build_html(args.session, streams, camera_range), encoding="utf-8")
    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
