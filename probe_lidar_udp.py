#!/usr/bin/env python3
"""Probe common UDP ports for incoming LiDAR packets."""

from __future__ import annotations

import argparse
import csv
import socket
import time
from pathlib import Path


DEFAULT_PORTS = "2368,2369,8308,7502,7503,6699,7788,8080,10110,13322"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe UDP ports for LiDAR traffic.")
    parser.add_argument(
        "--bind",
        default="0.0.0.0",
        help="Local IP address to bind. Use the LiDAR-facing interface IP if needed.",
    )
    parser.add_argument(
        "--ports",
        default=DEFAULT_PORTS,
        help="Comma-separated UDP ports or ranges to probe, for example 2368,7502-7503.",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=10.0,
        help="Seconds to listen.",
    )
    parser.add_argument(
        "--max-packet",
        type=int,
        default=65535,
        help="Maximum UDP packet size to receive.",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        help="Optional CSV file to write packet observations.",
    )
    parser.add_argument(
        "--include-loopback",
        action="store_true",
        help="Include packets from 127.0.0.0/8. By default they are ignored.",
    )
    return parser.parse_args()


def parse_ports(ports: str) -> list[int]:
    parsed: list[int] = []
    for item in ports.split(","):
        item = item.strip()
        if not item:
            continue

        if "-" in item:
            start_text, end_text = item.split("-", 1)
            start = int(start_text)
            end = int(end_text)
            parsed.extend(range(start, end + 1))
        else:
            parsed.append(int(item))

    return sorted(set(parsed))


def is_loopback(ip_address: str) -> bool:
    return ip_address.startswith("127.")


def open_socket(bind_ip: str, port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
    sock.setblocking(False)
    sock.bind((bind_ip, port))
    return sock


def main() -> int:
    args = parse_args()
    ports = parse_ports(args.ports)
    if not ports:
        print("No ports to probe.")
        return 1

    sockets: dict[int, socket.socket] = {}
    for port in ports:
        try:
            sockets[port] = open_socket(args.bind, port)
        except OSError as error:
            print(f"Could not bind {args.bind}:{port}: {error}")

    if not sockets:
        print("No UDP sockets could be opened.")
        return 1

    csv_file = None
    writer = None
    if args.csv is not None:
        csv_file = args.csv.open("w", newline="", encoding="utf-8")
        writer = csv.DictWriter(
            csv_file,
            fieldnames=[
                "monotonic_ns",
                "system_ns",
                "port",
                "source_ip",
                "source_port",
                "size",
            ],
        )
        writer.writeheader()

    counts = {port: 0 for port in sockets}
    bytes_by_port = {port: 0 for port in sockets}
    ignored_loopback = {port: 0 for port in sockets}
    sources: dict[int, set[tuple[str, int]]] = {port: set() for port in sockets}
    deadline = time.monotonic() + args.duration

    print(f"Listening on {args.bind} for {args.duration:.1f}s")
    print("Ports:", ", ".join(str(port) for port in sockets))

    try:
        while time.monotonic() < deadline:
            any_packet = False
            for port, sock in sockets.items():
                while True:
                    try:
                        payload, address = sock.recvfrom(args.max_packet)
                    except BlockingIOError:
                        break

                    any_packet = True
                    if not args.include_loopback and is_loopback(address[0]):
                        ignored_loopback[port] += 1
                        continue

                    counts[port] += 1
                    bytes_by_port[port] += len(payload)
                    sources[port].add((address[0], address[1]))
                    if writer is not None:
                        writer.writerow(
                            {
                                "monotonic_ns": time.monotonic_ns(),
                                "system_ns": time.time_ns(),
                                "port": port,
                                "source_ip": address[0],
                                "source_port": address[1],
                                "size": len(payload),
                            }
                        )

            if not any_packet:
                time.sleep(0.005)
    finally:
        for sock in sockets.values():
            sock.close()
        if csv_file is not None:
            csv_file.close()

    print("Results:")
    found = False
    for port in sorted(sockets):
        count = counts[port]
        if count:
            found = True
        source_text = ", ".join(f"{ip}:{src_port}" for ip, src_port in sorted(sources[port]))
        print(
            f"- {port}: packets={count}, bytes={bytes_by_port[port]}, "
            f"sources={source_text or '-'}, "
            f"ignored_loopback={ignored_loopback[port]}"
        )

    if not found:
        print("No UDP packets received on the probed ports.")
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
