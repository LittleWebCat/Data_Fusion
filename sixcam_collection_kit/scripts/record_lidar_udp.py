#!/usr/bin/env python3
"""Record one or more LiDAR UDP streams with monotonic/system timestamps."""

from __future__ import annotations

import argparse
import csv
import json
import multiprocessing as mp
import queue
import signal
import socket
import struct
import threading
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Record LiDAR UDP packets.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--bind", default="0.0.0.0")
    parser.add_argument("--port", type=int, action="append", required=True)
    parser.add_argument("--name", default="lidar")
    parser.add_argument("--max-packet", type=int, default=65535)
    parser.add_argument("--rcvbuf", type=int, default=16 * 1024 * 1024)
    parser.add_argument("--writer-queue", type=int, default=8192)
    parser.add_argument("--metadata-only", action="store_true")
    parser.add_argument("--duration", type=float)
    return parser.parse_args()


def sanitize_filename(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "_.-" else "_" for ch in value)
    cleaned = cleaned.strip("_")
    return cleaned or "lidar"


def lidar_binary_writer(binary_path: str, write_queue: mp.Queue) -> None:
    with open(binary_path, "wb") as binary_file:
        while True:
            item = write_queue.get()
            if item is None:
                break

            monotonic_ns, system_time_ns, payload = item
            binary_file.write(struct.pack("<QQI", monotonic_ns, system_time_ns, len(payload)))
            binary_file.write(payload)


class LidarUdpRecorder:
    def __init__(
        self,
        output_dir: Path,
        bind_ip: str,
        port: int,
        name: str,
        max_packet_size: int,
        receive_buffer_size: int,
        metadata_only: bool,
        writer_queue_size: int,
    ) -> None:
        self.output_dir = output_dir
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
        self.binary_path = output_dir / f"{self.name}_udp.bin"
        self.write_queue: mp.Queue | None = None
        self.writer_process: mp.Process | None = None

        if not metadata_only:
            context = mp.get_context("spawn")
            self.write_queue = context.Queue(maxsize=writer_queue_size)
            self.writer_process = context.Process(
                target=lidar_binary_writer,
                args=(str(self.binary_path), self.write_queue),
                name=f"{self.name}-binary-writer",
            )

        self.metadata_path = output_dir / f"{self.name}_udp.csv"
        self.metadata_file = self.metadata_path.open("w", newline="", encoding="utf-8")
        self.metadata = csv.DictWriter(
            self.metadata_file,
            fieldnames=[
                "packet_index",
                "monotonic_ns",
                "system_time_ns",
                "source_ip",
                "source_port",
                "destination_port",
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
            system_time_ns = time.time_ns()
            offset = -1
            raw_dropped = 0

            if self.write_queue is not None:
                offset = self.raw_offset
                try:
                    self.write_queue.put_nowait((monotonic_ns, system_time_ns, payload))
                    self.raw_offset += 20 + len(payload)
                except queue.Full:
                    offset = -1
                    raw_dropped = 1
                    self.raw_dropped_count += 1

            self.metadata.writerow(
                {
                    "packet_index": self.packet_count,
                    "monotonic_ns": monotonic_ns,
                    "system_time_ns": system_time_ns,
                    "source_ip": address[0],
                    "source_port": address[1],
                    "destination_port": self.port,
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

    def summary(self) -> dict[str, object]:
        return {
            "name": self.name,
            "bind_ip": self.bind_ip,
            "destination_port": self.port,
            "metadata_csv": self.metadata_path.name,
            "binary_file": self.binary_path.name if not self.metadata_only else None,
            "packets": self.packet_count,
            "bytes": self.byte_count,
            "raw_dropped": self.raw_dropped_count,
        }


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    stop_requested = False

    def request_stop(signum: int, _frame: object) -> None:
        nonlocal stop_requested
        stop_requested = True
        print(f"Received signal {signum}; stopping LiDAR recorder...", flush=True)

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    start_monotonic_ns = time.monotonic_ns()
    start_system_time_ns = time.time_ns()
    recorders: list[LidarUdpRecorder] = []

    try:
        for port in args.port:
            stream_name = args.name if len(args.port) == 1 else f"{args.name}_{port}"
            recorder = LidarUdpRecorder(
                output_dir=args.output_dir,
                bind_ip=args.bind,
                port=port,
                name=stream_name,
                max_packet_size=args.max_packet,
                receive_buffer_size=args.rcvbuf,
                metadata_only=args.metadata_only,
                writer_queue_size=args.writer_queue,
            )
            recorder.start()
            recorders.append(recorder)
            print(f"Recording LiDAR UDP on {args.bind}:{port} as {stream_name}", flush=True)

        deadline = None if args.duration is None else time.monotonic() + args.duration
        while not stop_requested:
            if deadline is not None and time.monotonic() >= deadline:
                break
            time.sleep(0.1)
    finally:
        for recorder in recorders:
            recorder.close()
            print(
                f"LiDAR {recorder.name}: packets={recorder.packet_count}, "
                f"bytes={recorder.byte_count}, raw_dropped={recorder.raw_dropped_count}",
                flush=True,
            )

        manifest = {
            "created_system_time_ns": start_system_time_ns,
            "created_monotonic_ns": start_monotonic_ns,
            "ended_system_time_ns": time.time_ns(),
            "ended_monotonic_ns": time.monotonic_ns(),
            "bind_ip": args.bind,
            "ports": args.port,
            "metadata_only": args.metadata_only,
            "max_packet": args.max_packet,
            "rcvbuf": args.rcvbuf,
            "writer_queue": args.writer_queue,
            "streams": [recorder.summary() for recorder in recorders],
        }
        (args.output_dir / "lidar_manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
