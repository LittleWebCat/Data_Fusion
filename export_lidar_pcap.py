#!/usr/bin/env python3
"""Export recorded LiDAR UDP streams to a PCAP file."""

from __future__ import annotations

import argparse
import csv
import socket
import struct
from pathlib import Path


PCAP_GLOBAL_HEADER = struct.pack(
    "<IHHIIII",
    0xA1B2C3D4,
    2,
    4,
    0,
    0,
    65535,
    1,
)
ETHERNET_HEADER = b"\x02\x00\x00\x00\x00\x02" + b"\x02\x00\x00\x00\x00\x01" + b"\x08\x00"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export LiDAR UDP recordings to PCAP.")
    parser.add_argument("session", type=Path, help="Recording session directory.")
    parser.add_argument(
        "--output",
        type=Path,
        help="Output PCAP path. Defaults to lidar.pcap in the session.",
    )
    parser.add_argument(
        "--dst-ip",
        default="169.254.1.100",
        help="Destination IP address used in the reconstructed PCAP.",
    )
    return parser.parse_args()


def checksum(data: bytes) -> int:
    if len(data) % 2:
        data += b"\x00"

    total = sum(struct.unpack(f"!{len(data) // 2}H", data))
    total = (total >> 16) + (total & 0xFFFF)
    total += total >> 16
    return (~total) & 0xFFFF


def destination_port(metadata_path: Path) -> int:
    name = metadata_path.name.removesuffix("_udp.csv")
    for part in reversed(name.split("_")):
        if part.isdigit():
            return int(part)
    raise ValueError(f"Could not infer destination port from {metadata_path.name}")


def read_payload(binary_file, offset: int, expected_size: int) -> bytes:
    binary_file.seek(offset)
    monotonic_ns, system_ns, size = struct.unpack("<QQI", binary_file.read(20))
    if size != expected_size:
        raise ValueError(f"Binary packet size mismatch: {size} != {expected_size}")
    return binary_file.read(size)


def build_packet(
    src_ip: str,
    dst_ip: str,
    src_port: int,
    dst_port: int,
    payload: bytes,
    packet_id: int,
) -> bytes:
    src_ip_bytes = socket.inet_aton(src_ip)
    dst_ip_bytes = socket.inet_aton(dst_ip)
    udp_length = 8 + len(payload)
    ip_length = 20 + udp_length

    ip_header = struct.pack(
        "!BBHHHBBH4s4s",
        0x45,
        0,
        ip_length,
        packet_id & 0xFFFF,
        0,
        64,
        socket.IPPROTO_UDP,
        0,
        src_ip_bytes,
        dst_ip_bytes,
    )
    ip_header = ip_header[:10] + struct.pack("!H", checksum(ip_header)) + ip_header[12:]
    udp_header = struct.pack("!HHHH", src_port, dst_port, udp_length, 0)
    return ETHERNET_HEADER + ip_header + udp_header + payload


def iter_metadata(metadata_path: Path):
    with metadata_path.open(newline="", encoding="utf-8") as metadata_file:
        for row in csv.DictReader(metadata_file):
            if int(row.get("raw_dropped", "0") or "0"):
                continue
            offset = int(row["binary_offset"])
            if offset < 0:
                continue
            yield row


def main() -> int:
    args = parse_args()
    output_path = args.output or args.session / "lidar.pcap"
    metadata_paths = sorted(args.session.glob("*_udp.csv"))
    if not metadata_paths:
        print(f"No LiDAR metadata files found in {args.session}")
        return 1

    records = []
    for metadata_path in metadata_paths:
        binary_path = args.session / metadata_path.name.replace("_udp.csv", "_udp.bin")
        if not binary_path.exists():
            print(f"Skipping {metadata_path.name}: missing {binary_path.name}")
            continue

        dst_port = destination_port(metadata_path)
        with binary_path.open("rb") as binary_file:
            for row in iter_metadata(metadata_path):
                payload = read_payload(binary_file, int(row["binary_offset"]), int(row["size"]))
                records.append(
                    (
                        int(row["system_ns"]),
                        row["source_ip"],
                        args.dst_ip,
                        int(row["source_port"]),
                        dst_port,
                        payload,
                    )
                )

    if not records:
        print("No raw LiDAR packets available to export.")
        return 1

    records.sort(key=lambda item: item[0])
    with output_path.open("wb") as output_file:
        output_file.write(PCAP_GLOBAL_HEADER)
        for packet_id, (system_ns, src_ip, dst_ip, src_port, dst_port, payload) in enumerate(records):
            packet = build_packet(src_ip, dst_ip, src_port, dst_port, payload, packet_id)
            sec = system_ns // 1_000_000_000
            usec = (system_ns % 1_000_000_000) // 1_000
            output_file.write(struct.pack("<IIII", sec, usec, len(packet), len(packet)))
            output_file.write(packet)

    print(f"Wrote {output_path} with {len(records)} packets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
