"""Delta-packet codec for the lighting stream.

Instead of sending video, the server sends a quantised difference between the
current lighting buffer and the previous one, plus the camera pose it was
rendered for. The client uses the pose to reproject the buffer onto its own,
newer camera.

Wire format (little endian):
    header : magic u16 | frame u32 | flags u8 | pose 7*f32 | count u32
    body   : count * (index u32, delta i8)   # sparse: only changed cells
"""
from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

import numpy as np

MAGIC = 0xA7E1
KEYFRAME = 0x01
_HEADER = struct.Struct("<HIB7fI")
SCALE = 1 / 32  # one quantisation step in lighting units


@dataclass
class Packet:
    frame: int
    keyframe: bool
    pose: tuple[float, ...]  # x, y, z, qx, qy, qz, qw
    cells: np.ndarray        # int8 deltas (dense) or absolute values on keyframes


def _quantise(buf: np.ndarray) -> np.ndarray:
    return np.clip(np.round(buf / SCALE), -127, 127).astype(np.int8)


def encode(frame: int, buf: np.ndarray, prev: np.ndarray | None,
           pose: tuple[float, ...]) -> bytes:
    if len(pose) != 7:
        raise ValueError("pose must be position(3) + quaternion(4)")
    q = _quantise(buf.ravel())
    keyframe = prev is None
    ref = np.zeros_like(q) if keyframe else _quantise(prev.ravel())
    # int16 intermediate so the subtraction cannot wrap before clipping
    delta = np.clip(q.astype(np.int16) - ref.astype(np.int16), -127, 127).astype(np.int8)
    idx = np.flatnonzero(delta).astype("<u4")
    head = _HEADER.pack(MAGIC, frame, KEYFRAME if keyframe else 0, *pose, len(idx))
    body = np.empty(len(idx), dtype=[("i", "<u4"), ("d", "i1")])
    body["i"], body["d"] = idx, delta[idx]
    return head + zlib.compress(body.tobytes(), 1)


def decode(data: bytes, size: int) -> Packet:
    magic, frame, flags, *rest, count = _HEADER.unpack_from(data)
    if magic != MAGIC:
        raise ValueError("bad magic")
    body = np.frombuffer(zlib.decompress(data[_HEADER.size:]),
                         dtype=[("i", "<u4"), ("d", "i1")])
    if len(body) != count:
        raise ValueError("corrupt packet: cell count mismatch")
    cells = np.zeros(size, dtype=np.int8)
    cells[body["i"]] = body["d"]
    return Packet(frame, bool(flags & KEYFRAME), tuple(rest), cells)


class Reconstructor:
    """Client-side state that accumulates deltas back into a lighting buffer."""

    def __init__(self, size: int):
        self.state = np.zeros(size, dtype=np.int16)
        self.last_frame = -1

    def apply(self, pkt: Packet) -> np.ndarray:
        if not pkt.keyframe and pkt.frame != self.last_frame + 1:
            raise ValueError("gap in delta chain; request a keyframe")
        if pkt.keyframe:
            self.state[:] = 0
        self.state += pkt.cells
        self.last_frame = pkt.frame
        return np.clip(self.state, -127, 127).astype(np.float32) * SCALE
