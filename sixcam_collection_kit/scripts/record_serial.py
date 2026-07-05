#!/usr/bin/env python3
"""Record a serial stream with monotonic/system timestamps."""

from __future__ import annotations

import argparse
import csv
import fcntl
import json
import os
import select
import struct
import signal
import termios
import time
from pathlib import Path


BAUD_RATES = {
    9600: termios.B9600,
    19200: termios.B19200,
    38400: termios.B38400,
    57600: termios.B57600,
    115200: termios.B115200,
    230400: termios.B230400,
    460800: termios.B460800,
    500000: termios.B500000,
    921600: termios.B921600,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Record timestamped serial data.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--device", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--read-size", type=int, default=4096)
    parser.add_argument("--duration", type=float)
    return parser.parse_args()


def sanitize_filename(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "_.-" else "_" for ch in value)
    cleaned = cleaned.strip("_")
    return cleaned or "serial"


def configure_serial(fd: int, baud: int) -> None:
    if baud not in BAUD_RATES:
        supported = ", ".join(str(value) for value in sorted(BAUD_RATES))
        raise ValueError(f"Unsupported baud {baud}; supported: {supported}")

    attrs = termios.tcgetattr(fd)
    attrs[0] = 0
    attrs[1] = 0
    attrs[2] = termios.CLOCAL | termios.CREAD | termios.CS8
    attrs[3] = 0
    attrs[4] = BAUD_RATES[baud]
    attrs[5] = BAUD_RATES[baud]
    attrs[6][termios.VMIN] = 0
    attrs[6][termios.VTIME] = 1
    termios.tcsetattr(fd, termios.TCSANOW, attrs)

    modem_bits = 0
    for bit_name in ("TIOCM_DTR", "TIOCM_RTS"):
        modem_bits |= getattr(termios, bit_name, 0)
    if modem_bits:
        try:
            fcntl.ioctl(fd, termios.TIOCMBIS, struct.pack("I", modem_bits))
        except OSError:
            pass


def preview_text(payload: bytes) -> str:
    text = payload.decode("utf-8", errors="replace")
    text = text.replace("\r", "\\r").replace("\n", "\\n")
    return text[:240]


def main() -> int:
    args = parse_args()
    name = sanitize_filename(args.name)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    stop_requested = False

    def request_stop(signum: int, _frame: object) -> None:
        nonlocal stop_requested
        stop_requested = True
        print(f"Received signal {signum}; stopping {name} serial recorder...", flush=True)

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    metadata_path = args.output_dir / f"{name}_serial.csv"
    binary_path = args.output_dir / f"{name}_serial.bin"
    manifest_path = args.output_dir / f"{name}_serial_manifest.json"

    start_monotonic_ns = time.monotonic_ns()
    start_system_time_ns = time.time_ns()
    chunk_count = 0
    byte_count = 0
    raw_offset = 0

    fd = os.open(args.device, os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK)
    try:
        configure_serial(fd, args.baud)
        deadline = None if args.duration is None else time.monotonic() + args.duration

        with metadata_path.open("w", newline="", encoding="utf-8") as metadata_file:
            writer = csv.DictWriter(
                metadata_file,
                fieldnames=[
                    "chunk_index",
                    "monotonic_ns",
                    "system_time_ns",
                    "size",
                    "binary_offset",
                    "text_preview",
                ],
            )
            writer.writeheader()

            with binary_path.open("wb") as binary_file:
                print(
                    f"Recording serial {args.device} at {args.baud} baud as {name}",
                    flush=True,
                )
                while not stop_requested:
                    if deadline is not None and time.monotonic() >= deadline:
                        break

                    readable, _, _ = select.select([fd], [], [], 0.25)
                    if not readable:
                        continue

                    try:
                        payload = os.read(fd, args.read_size)
                    except BlockingIOError:
                        continue
                    if not payload:
                        continue

                    monotonic_ns = time.monotonic_ns()
                    system_time_ns = time.time_ns()
                    binary_file.write(payload)
                    writer.writerow(
                        {
                            "chunk_index": chunk_count,
                            "monotonic_ns": monotonic_ns,
                            "system_time_ns": system_time_ns,
                            "size": len(payload),
                            "binary_offset": raw_offset,
                            "text_preview": preview_text(payload),
                        }
                    )
                    chunk_count += 1
                    byte_count += len(payload)
                    raw_offset += len(payload)
    finally:
        os.close(fd)

    manifest = {
        "created_system_time_ns": start_system_time_ns,
        "created_monotonic_ns": start_monotonic_ns,
        "ended_system_time_ns": time.time_ns(),
        "ended_monotonic_ns": time.monotonic_ns(),
        "name": name,
        "device": args.device,
        "baud": args.baud,
        "metadata_csv": metadata_path.name,
        "binary_file": binary_path.name,
        "chunks": chunk_count,
        "bytes": byte_count,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Serial {name}: chunks={chunk_count}, bytes={byte_count}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
