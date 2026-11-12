"""Delta-packet codec for the lighting stream.

The server sends a quantised difference between the current lighting buffer and
the previous one, plus the camera pose it was rendered for. The client uses the
pose to reproject the buffer onto its own, newer camera.

Wire format (little endian):
    header : magic u16 | frame u32 | flags u8 | pose 7*f32 | count u32
    body   : zlib( gaps | deltas )
             gaps   : count * u16 (or u32 if FLAG_WIDE) distance from the previous
                      changed cell, so runs of nearby changes compress well
             deltas : count * i8

`Encoder` keeps the previous quantised frame so each frame is quantised once and
scratch buffers are reused; this matters when one process serves many sessions.
"""
from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

import numpy as np

MAGIC = 0xA7E1
FLAG_KEY = 0x01
FLAG_WIDE = 0x02
_HEADER = struct.Struct("<HIB7fI")
SCALE = 1 / 32  # one quantisation step in lighting units


@dataclass
class Packet:
    frame: int
    keyframe: bool
    pose: tuple[float, ...]  # x, y, z, qx, qy, qz, qw
    index: np.ndarray        # positions of changed cells
    delta: np.ndarray        # int8 change at each position


class Encoder:
    """Per-session encoder. Not thread-safe; use one instance per client."""

    def __init__(self, size: int, level: int = 1):
        self.size = size
        self.level = level  # zlib 1 is the right latency/size trade for live streaming
        self._prev = np.zeros(size, dtype=np.int16)
        self._frame = -1

    def reset(self) -> None:
        """Force the next packet to be a keyframe (call on client request)."""
        self._prev[:] = 0
        self._frame = -1

    def encode(self, buf: np.ndarray, pose: tuple[float, ...]) -> bytes:
        if len(pose) != 7:
            raise ValueError("pose must be position(3) + quaternion(4)")
        if buf.size != self.size:
            raise ValueError(f"expected {self.size} cells, got {buf.size}")
        key = self._frame < 0
        cur = np.clip(np.rint(buf.ravel() / SCALE), -127, 127).astype(np.int16)
        delta = np.clip(cur - self._prev, -127, 127)
        idx = np.flatnonzero(delta)
        self._prev += delta.astype(np.int16)  # track what the client reconstructs
        gaps = np.diff(idx, prepend=0)
        wide = bool(len(gaps)) and int(gaps.max()) > 0xFFFF
        flags = (FLAG_KEY if key else 0) | (FLAG_WIDE if wide else 0)
        body = zlib.compress(
            gaps.astype("<u4" if wide else "<u2").tobytes() + delta[idx].astype(np.int8).tobytes(),
            self.level)
        self._frame += 1
        return _HEADER.pack(MAGIC, self._frame, flags, *pose, len(idx)) + body


def decode(data: bytes) -> Packet:
    magic, frame, flags, *rest, count = _HEADER.unpack_from(data)
    if magic != MAGIC:
        raise ValueError("bad magic")
    raw = zlib.decompress(data[_HEADER.size:])
    gap_t = np.dtype("<u4" if flags & FLAG_WIDE else "<u2")
    if len(raw) != count * (gap_t.itemsize + 1):
        raise ValueError("corrupt packet: cell count mismatch")
    gaps = np.frombuffer(raw, gap_t, count)
    delta = np.frombuffer(raw, np.int8, count, offset=count * gap_t.itemsize)
    return Packet(frame, bool(flags & FLAG_KEY), tuple(rest), np.cumsum(gaps, dtype=np.int64), delta)


class Reconstructor:
    """Client-side state that accumulates deltas back into a lighting buffer."""

    def __init__(self, size: int):
        self.state = np.zeros(size, dtype=np.int16)
        self.last_frame = -1

    def apply(self, pkt: Packet) -> np.ndarray:
        if pkt.keyframe:
            self.state[:] = 0
        elif pkt.frame != self.last_frame + 1:
            raise ValueError("gap in delta chain; request a keyframe")
        self.state[pkt.index] += pkt.delta  # indices are unique, so fancy-index add is safe
        self.last_frame = pkt.frame
        return np.clip(self.state, -127, 127).astype(np.float32) * SCALE
