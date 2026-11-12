"""Asyncio TCP lighting streamer (stdlib only).

Each client gets its own Encoder. Frames are length-prefixed (u32). A client that
cannot keep up is never allowed to stall the producer: only the newest frame is
kept per session, and stale ones are dropped, because old lighting is worthless.
After a drop the next packet is a keyframe so the client's delta chain stays valid.

    python server/streaming/server.py --port 9000 --fps 60
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import struct
import time

import numpy as np

from delta_packets import Encoder

log = logging.getLogger("streamer")
LEN = struct.Struct("<I")
W, H, C = 320, 180, 3


def synth_frame(t: float, out: np.ndarray) -> np.ndarray:
    """Stand-in for the real lighting renderer: a few moving soft blobs."""
    y, x = np.mgrid[0:H, 0:W].astype(np.float32)
    out[:] = 0
    for k in range(3):
        cx = W / 2 + np.sin(t * (0.6 + 0.3 * k) + k) * W / 3
        cy = H / 2 + np.cos(t * (0.5 + 0.2 * k)) * H / 3
        out[..., k] += 2.0 * np.exp(-(((x - cx) ** 2 + (y - cy) ** 2) / 600))
    return out


class Session:
    def __init__(self, writer: asyncio.StreamWriter):
        self.writer = writer
        self.enc = Encoder(W * H * C)
        self.latest: bytes | None = None
        self.dropped = 0
        self.need_key = False


class Streamer:
    def __init__(self, fps: int):
        self.fps = fps
        self.sessions: set[Session] = set()
        self.frames = 0
        self._buf = np.zeros((H, W, C), dtype=np.float32)

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        s = Session(writer)
        self.sessions.add(s)
        peer = writer.get_extra_info("peername")
        log.info("client connected %s (%d active)", peer, len(self.sessions))
        sender = asyncio.create_task(self._send_loop(s))
        try:
            while await reader.read(64):  # any bytes from client = keyframe request
                s.enc.reset()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            sender.cancel()
            self.sessions.discard(s)
            writer.close()
            log.info("client left %s", peer)

    async def _send_loop(self, s: Session):
        while True:
            await asyncio.sleep(1 / (self.fps * 2))
            data, s.latest = s.latest, None
            if data is None:
                continue
            if s.writer.transport.get_write_buffer_size() > 256 * 1024:
                s.dropped += 1  # client is behind: skip, resync with a keyframe
                s.enc.reset()
                continue
            s.writer.write(LEN.pack(len(data)) + data)

    async def produce(self):
        period, t0 = 1 / self.fps, time.perf_counter()
        nxt = t0
        while True:
            now = time.perf_counter()
            frame = synth_frame(now - t0, self._buf)
            pose = (0.0, 1.6, 0.0, 0.0, 0.0, 0.0, 1.0)
            for s in self.sessions:
                s.latest = s.enc.encode(frame, pose)
            self.frames += 1
            nxt += period
            await asyncio.sleep(max(0.0, nxt - time.perf_counter()))  # fixed-rate, no drift

    async def stats(self):
        while True:
            await asyncio.sleep(10)
            log.info("frames=%d sessions=%d dropped=%d", self.frames, len(self.sessions),
                     sum(s.dropped for s in self.sessions))


async def serve(host: str, port: int, fps: int):
    st = Streamer(fps)
    server = await asyncio.start_server(st.handle, host, port)
    tasks = [asyncio.create_task(st.produce()), asyncio.create_task(st.stats())]
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):  # clean shutdown under an orchestrator
        loop.add_signal_handler(sig, stop.set)
    log.info("listening on %s:%d at %d fps", host, port, fps)
    await stop.wait()
    for t in tasks:
        t.cancel()
    server.close()
    await server.wait_closed()
    for s in list(st.sessions):
        s.writer.close()


async def read_packet(reader: asyncio.StreamReader) -> bytes:
    (n,) = LEN.unpack(await reader.readexactly(LEN.size))
    return await reader.readexactly(n)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=9000)
    ap.add_argument("--fps", type=int, default=60)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(serve(a.host, a.port, a.fps))
