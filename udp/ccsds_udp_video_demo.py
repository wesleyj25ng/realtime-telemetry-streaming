#!/usr/bin/env python3
"""
ccsds_udp_video_demo.py

Public-safe demo: MP4 -> JPEG bytes -> CCSDS-style segmented UDP packets -> reassembly -> display/save.

Features:
- CCSDS-like primary header fields (version/type/sec_hdr/apid + seq flags/count + pkt length)
- Fixed-size payload chunks (default 232 bytes)
- Segmentation flags: 01 first, 00 continuation, 10 last
- UDP sender/receiver
- Receiver reassembles a frame, reports missing segments, decodes JPEG
- Optional packet-drop simulation on send

Dependencies:
  pip install opencv-python numpy PyTurboJPEG

Notes:
- For TurboJPEG, you can either:
  (A) provide --tjlib path to the native turbojpeg library, OR
  (B) omit --tjlib and let PyTurboJPEG find it (works on many systems)

Usage:
  # Terminal 1: receiver
  python ccsds_udp_video_demo.py recv --bind 127.0.0.1 --port 2020 --show

  # Terminal 2: sender
  python ccsds_udp_video_demo.py send --dest 127.0.0.1 --port 2020 --mp4 path/to/video.mp4

  # Simulate drops (drop segment indices within each JPEG frame)
  python ccsds_udp_video_demo.py send --dest 127.0.0.1 --port 2020 --mp4 video.mp4 --drop "5,6,12"

  # Save reconstructed stream to AVI (receiver side)
  python ccsds_udp_video_demo.py recv --bind 127.0.0.1 --port 2020 --out reconstruct.avi
"""

from __future__ import annotations

import argparse
import socket
import struct
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
from turbojpeg import TurboJPEG, TJSAMP_420, TJFLAG_FASTDCT, TJFLAG_FASTUPSAMPLE


# ------------------------------
# CCSDS-like header packing
# ------------------------------
PRIMARY_LEN = 6

# Segmentation flags (2-bit)
SEG_FIRST = 0b01
SEG_CONT  = 0b00
SEG_LAST  = 0b10

DEFAULT_PAYLOAD_CHUNK = 232


@dataclass
class CCSDSPrimary:
    packet_id: int       # 16-bit
    seq_control: int     # 16-bit (flags+seq_count)
    pkt_len: int         # 16-bit (bytes after primary - 1)


def pack_primary(apid: int, seg_flag: int, seq_count: int, bytes_after_primary: int) -> bytes:
    """
    Primary header:
      packet_id: version(3) type(1) secHdr(1) apid(11)
      seq_ctrl:  seg_flag(2) seq_count(14)
      pkt_len:   (bytes_after_primary - 1)
    """
    version = 0
    pkt_type = 0
    sec_hdr_flag = 1

    packet_id = ((version & 0x7) << 13) | ((pkt_type & 0x1) << 12) | ((sec_hdr_flag & 0x1) << 11) | (apid & 0x7FF)
    seq_control = ((seg_flag & 0x3) << 14) | (seq_count & 0x3FFF)
    pkt_len = (bytes_after_primary - 1) & 0xFFFF

    return struct.pack(">HHH", packet_id, seq_control, pkt_len)


def unpack_primary(b: bytes) -> CCSDSPrimary:
    packet_id, seq_control, pkt_len = struct.unpack(">HHH", b[:PRIMARY_LEN])
    return CCSDSPrimary(packet_id=packet_id, seq_control=seq_control, pkt_len=pkt_len)


def get_seg_flag(seq_control: int) -> int:
    return (seq_control >> 14) & 0x3


def get_seq_count(seq_control: int) -> int:
    return seq_control & 0x3FFF


# ------------------------------
# Sender
# ------------------------------
def parse_drop_list(s: Optional[str]) -> List[int]:
    if not s:
        return []
    out: List[int] = []
    for part in s.split(","):
        part = part.strip()
        if part:
            out.append(int(part))
    return out


def send_packet(dest: str, port: int, pkt: bytes, sock: socket.socket) -> None:
    sock.sendto(pkt, (dest, port))


def encode_jpeg(jpeg: TurboJPEG, frame_bgr: np.ndarray, quality: int = 70) -> bytes:
    flags = TJFLAG_FASTDCT | TJFLAG_FASTUPSAMPLE
    return jpeg.encode(frame_bgr, quality=quality, jpeg_subsample=TJSAMP_420, flags=flags)


def segment_bytes(data: bytes, chunk: int) -> List[bytes]:
    return [data[i:i + chunk] for i in range(0, len(data), chunk)] or [b""]


def send_video(
    dest: str,
    port: int,
    mp4_path: str,
    jpeg: TurboJPEG,
    apid: int,
    chunk: int,
    every_nth_frame: int,
    drop_segments: List[int],
    delay_ms: int,
) -> None:
    cap = cv2.VideoCapture(mp4_path)
    if not cap.isOpened():
        raise SystemExit(f"Could not open video: {mp4_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_idx = 0

    print(f"[send] mp4={mp4_path} fps={fps:.2f} dest={dest}:{port} chunk={chunk} every_nth={every_nth_frame}")
    if drop_segments:
        print(f"[send] simulating drops for segment indices: {drop_segments}")

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("[send] end of video")
                break

            if every_nth_frame > 1 and (frame_idx % every_nth_frame != 0):
                frame_idx += 1
                continue

            jpeg_bytes = encode_jpeg(jpeg, frame)
            segs = segment_bytes(jpeg_bytes, chunk)
            total = len(segs)

            # Send all segments for this frame with per-frame seq_count starting at 0
            expected_last = total - 1
            for seg_index, payload in enumerate(segs):
                if seg_index == 0:
                    seg_flag = SEG_FIRST
                elif seg_index == expected_last:
                    seg_flag = SEG_LAST
                else:
                    seg_flag = SEG_CONT

                seq_count = seg_index  # per-frame sequence

                if seg_index in drop_segments:
                    print(f"[send] drop seg={seg_index}/{expected_last} (simulated)")
                    continue

                # bytes after primary = payload_len (no secondary header in this demo)
                primary = pack_primary(apid=apid, seg_flag=seg_flag, seq_count=seq_count, bytes_after_primary=len(payload))
                pkt = primary + payload

                send_packet(dest, port, pkt, s)
                # print(f"[send] frame={frame_idx} seg={seg_index}/{expected_last} flag={seg_flag:02b} bytes={len(pkt)}")

                if delay_ms > 0:
                    time.sleep(delay_ms / 1000.0)

            frame_idx += 1


# ------------------------------
# Receiver / Reassembly
# ------------------------------
@dataclass
class FrameState:
    chunks: Dict[int, bytes]
    last_seen: float
    started: float
    saw_last: bool
    last_index: Optional[int]


def recv_stream(
    bind: str,
    port: int,
    timeout_s: float,
    jpeg: TurboJPEG,
    show: bool,
    out_path: Optional[str],
    fps: float,
) -> None:
    writer = None

    state = FrameState(chunks={}, last_seen=time.time(), started=time.time(), saw_last=False, last_index=None)
    frame_no = 0

    def finalize_frame() -> None:
        nonlocal state, writer, frame_no

        if state.last_index is None:
            return

        missing = [i for i in range(state.last_index + 1) if i not in state.chunks]
        if missing:
            print(f"[recv] frame={frame_no:04d} INCOMPLETE missing={missing}")
        else:
            blob = b"".join(state.chunks[i] for i in range(state.last_index + 1))
            try:
                img = jpeg.decode(blob)
            except Exception as e:
                print(f"[recv] frame={frame_no:04d} decode failed: {e}")
                img = None

            if img is not None:
                print(f"[recv] frame={frame_no:04d} OK bytes={len(blob)}")
                if out_path:
                    if writer is None:
                        h, w = img.shape[:2]
                        fourcc = cv2.VideoWriter_fourcc(*"MJPG")
                        writer = cv2.VideoWriter(out_path, fourcc, fps, (w, h))
                        if not writer.isOpened():
                            raise SystemExit(f"Could not open video writer: {out_path}")
                    writer.write(img)

                if show:
                    cv2.imshow("Reconstructed Stream", img)
                    cv2.waitKey(1)

        # Reset for next frame
        frame_no += 1
        state = FrameState(chunks={}, last_seen=time.time(), started=time.time(), saw_last=False, last_index=None)

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind((bind, port))
        s.settimeout(timeout_s)
        print(f"[recv] listening on {bind}:{port} timeout={timeout_s}s")

        try:
            while True:
                try:
                    data, _ = s.recvfrom(65535)
                except socket.timeout:
                    print("[recv] timeout reached (no packets). stopping.")
                    break

                if len(data) < PRIMARY_LEN:
                    continue

                primary = unpack_primary(data)
                seg_flag = get_seg_flag(primary.seq_control)
                seq = get_seq_count(primary.seq_control)
                payload = data[PRIMARY_LEN:]

                state.last_seen = time.time()
                state.chunks[seq] = payload

                if seg_flag == SEG_LAST:
                    state.saw_last = True
                    state.last_index = seq

                # If we saw last, we can finalize immediately
                if state.saw_last and state.last_index is not None:
                    finalize_frame()

        finally:
            if writer:
                writer.release()
            if show:
                cv2.destroyAllWindows()


# ------------------------------
# CLI
# ------------------------------
def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="mode", required=True)

    send = sub.add_parser("send", help="send mp4 frames over UDP in CCSDS-style segments")
    send.add_argument("--dest", required=True)
    send.add_argument("--port", type=int, default=2020)
    send.add_argument("--mp4", required=True, help="path to an mp4 file")
    send.add_argument("--apid", type=int, default=1, help="demo APID (0-2047)")
    send.add_argument("--chunk", type=int, default=DEFAULT_PAYLOAD_CHUNK, help="payload bytes per packet segment")
    send.add_argument("--every-nth-frame", type=int, default=2, help="send every Nth frame (default 2)")
    send.add_argument("--drop", type=str, default=None, help='comma list of segment indices to drop per frame, e.g. "5,6,12"')
    send.add_argument("--delay-ms", type=int, default=0, help="optional delay between segments")
    send.add_argument("--tjlib", type=str, default=None, help="optional path to turbojpeg library")

    recv = sub.add_parser("recv", help="receive segments, reassemble frames, decode and show/save")
    recv.add_argument("--bind", default="127.0.0.1")
    recv.add_argument("--port", type=int, default=2020)
    recv.add_argument("--timeout", type=float, default=5.0)
    recv.add_argument("--show", action="store_true", help="display decoded frames")
    recv.add_argument("--out", type=str, default=None, help="optional output AVI path")
    recv.add_argument("--fps", type=float, default=30.0, help="fps used for output writer")
    recv.add_argument("--tjlib", type=str, default=None, help="optional path to turbojpeg library")

    args = ap.parse_args()

    jpeg = TurboJPEG(args.tjlib) if getattr(args, "tjlib", None) else TurboJPEG()

    if args.mode == "send":
        drops = parse_drop_list(args.drop)
        send_video(
            dest=args.dest,
            port=args.port,
            mp4_path=args.mp4,
            jpeg=jpeg,
            apid=args.apid,
            chunk=args.chunk,
            every_nth_frame=max(1, args.every_nth_frame),
            drop_segments=drops,
            delay_ms=args.delay_ms,
        )
    else:
        recv_stream(
            bind=args.bind,
            port=args.port,
            timeout_s=args.timeout,
            jpeg=jpeg,
            show=args.show,
            out_path=args.out,
            fps=args.fps,
        )


if __name__ == "__main__":
    main()