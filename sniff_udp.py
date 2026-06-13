#!/usr/bin/env python3
"""Sniff UDP packets on a network interface and summarize ports.

This uses a raw AF_PACKET socket on Linux, so it usually needs sudo or
CAP_NET_RAW.
"""

from __future__ import annotations

import argparse
import socket
import struct
import time
from collections import defaultdict


ETH_P_IP = 0x0800
ETH_P_8021Q = 0x8100
ETH_P_8021AD = 0x88A8
IPPROTO_UDP = 17


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sniff UDP packets on one interface.")
    parser.add_argument("interface", help="Network interface to sniff, for example eno1.")
    parser.add_argument(
        "--duration",
        type=float,
        default=10.0,
        help="Seconds to sniff.",
    )
    parser.add_argument(
        "--include-loopback",
        action="store_true",
        help="Include 127.0.0.0/8 traffic.",
    )
    parser.add_argument(
        "--source-ip",
        help="Only report packets from this source IP.",
    )
    parser.add_argument(
        "--min-packets",
        type=int,
        default=2,
        help="Only print flows with at least this many packets.",
    )
    parser.add_argument(
        "--show-one-offs",
        action="store_true",
        help="Print flows with one packet too.",
    )
    return parser.parse_args()


def ipv4(address: bytes) -> str:
    return socket.inet_ntoa(address)


def is_loopback(ip_address: str) -> bool:
    return ip_address.startswith("127.")


def parse_udp_packet(packet: bytes) -> tuple[str, str, int, int, int] | None:
    if len(packet) < 34:
        return None

    offset = 14
    eth_type = struct.unpack("!H", packet[12:14])[0]
    while eth_type in (ETH_P_8021Q, ETH_P_8021AD):
        if len(packet) < offset + 4:
            return None
        eth_type = struct.unpack("!H", packet[offset + 2 : offset + 4])[0]
        offset += 4

    if eth_type != ETH_P_IP:
        return None

    ip_start = offset
    if len(packet) < ip_start + 20:
        return None

    version_ihl = packet[ip_start]
    version = version_ihl >> 4
    ihl = (version_ihl & 0x0F) * 4
    if version != 4 or ihl < 20 or len(packet) < ip_start + ihl + 8:
        return None

    total_length = struct.unpack("!H", packet[ip_start + 2 : ip_start + 4])[0]
    if total_length < ihl + 8:
        return None
    if len(packet) < ip_start + min(total_length, ihl + 8):
        return None

    protocol = packet[ip_start + 9]
    if protocol != IPPROTO_UDP:
        return None

    flags_fragment = struct.unpack("!H", packet[ip_start + 6 : ip_start + 8])[0]
    fragment_offset = flags_fragment & 0x1FFF
    more_fragments = bool(flags_fragment & 0x2000)
    if fragment_offset != 0:
        return None

    src_ip = ipv4(packet[ip_start + 12 : ip_start + 16])
    dst_ip = ipv4(packet[ip_start + 16 : ip_start + 20])
    udp_start = ip_start + ihl
    src_port, dst_port, length = struct.unpack("!HHH", packet[udp_start : udp_start + 6])
    if src_port == 0 or dst_port == 0 or length < 8:
        return None
    if not more_fragments and length > total_length - ihl:
        return None

    return src_ip, dst_ip, src_port, dst_port, length


def main() -> int:
    args = parse_args()
    counts: dict[tuple[str, int, str, int], int] = defaultdict(int)
    bytes_by_flow: dict[tuple[str, int, str, int], int] = defaultdict(int)

    try:
        sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(ETH_P_IP))
        sock.bind((args.interface, 0))
        sock.settimeout(0.25)
    except PermissionError:
        print("Permission denied. Run with sudo or grant CAP_NET_RAW.")
        return 2
    except OSError as error:
        print(f"Could not sniff {args.interface}: {error}")
        return 1

    deadline = time.monotonic() + args.duration
    print(f"Sniffing UDP on {args.interface} for {args.duration:.1f}s")

    try:
        while time.monotonic() < deadline:
            try:
                packet = sock.recv(65535)
            except socket.timeout:
                continue

            parsed = parse_udp_packet(packet)
            if parsed is None:
                continue

            src_ip, dst_ip, src_port, dst_port, length = parsed
            if not args.include_loopback and (is_loopback(src_ip) or is_loopback(dst_ip)):
                continue
            if args.source_ip is not None and src_ip != args.source_ip:
                continue

            flow = (src_ip, src_port, dst_ip, dst_port)
            counts[flow] += 1
            bytes_by_flow[flow] += length
    finally:
        sock.close()

    min_packets = 1 if args.show_one_offs else args.min_packets
    printable = {
        flow: count for flow, count in counts.items() if count >= min_packets
    }

    if not printable:
        if counts:
            print(
                "UDP packets were seen, but no repeated flows matched the print threshold. "
                "Use --show-one-offs to print everything."
            )
        else:
            print("No UDP packets seen.")
        return 1

    print("UDP flows:")
    for flow, count in sorted(printable.items(), key=lambda item: item[1], reverse=True):
        src_ip, src_port, dst_ip, dst_port = flow
        print(
            f"- {src_ip}:{src_port} -> {dst_ip}:{dst_port}: "
            f"packets={count}, udp_bytes={bytes_by_flow[flow]}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
