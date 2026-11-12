import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "server" / "python"), str(ROOT / "server" / "streaming")]

from delta_packets import Encoder, Reconstructor, SCALE, decode  # noqa: E402
from partitioner import BASIC_LAPTOP, Partitioner, Tier  # noqa: E402
from simulator import simulate  # noqa: E402

POSE = (0, 1, 2, 0, 0, 0, 1)


def test_partition_respects_budget():
    p = Partitioner(BASIC_LAPTOP)
    plan = p.plan()
    totals = Partitioner.totals(plan)
    assert totals["client_gpu_ms"] <= p.gpu_budget_ms
    assert totals["client_vram_mb"] <= BASIC_LAPTOP.vram_budget_mb


def test_heavy_stages_stay_on_server():
    tiers = {pl.stage.stage_id: pl.tier for pl in Partitioner(BASIC_LAPTOP).plan()}
    assert tiers["S1"] is Tier.CLIENT
    assert tiers["S6"] is Tier.SERVER  # ray tracing: no hardware, low sensitivity
    assert tiers["S3"] is Tier.SERVER or tiers["S3"] is Tier.SPLIT


def test_tight_budget_pushes_work_to_server():
    tight = Partitioner(BASIC_LAPTOP, gpu_load_ratio=0.001).plan()
    assert sum(p.tier is Tier.CLIENT for p in tight) < 6


def test_invalid_ratio():
    with pytest.raises(ValueError):
        Partitioner(BASIC_LAPTOP, gpu_load_ratio=0)


def _roundtrip(enc, rec, buf):
    return rec.apply(decode(enc.encode(buf, POSE)))


def test_codec_roundtrip():
    rng = np.random.default_rng(1)
    a = rng.uniform(-2, 2, 4096).astype(np.float32)
    b = a + rng.normal(0, 0.05, a.shape).astype(np.float32) * (rng.random(4096) < 0.1)
    enc, rec = Encoder(a.size), Reconstructor(a.size)
    assert np.abs(_roundtrip(enc, rec, a) - a).max() <= SCALE
    assert np.abs(_roundtrip(enc, rec, b) - b).max() <= 2 * SCALE


def test_no_drift_over_many_frames():
    rng = np.random.default_rng(3)
    x = rng.uniform(-1, 1, 2048).astype(np.float32)
    enc, rec = Encoder(x.size), Reconstructor(x.size)
    for _ in range(300):
        x = np.clip(x + rng.normal(0, 0.03, x.shape).astype(np.float32), -3, 3)
        out = _roundtrip(enc, rec, x)
    assert np.abs(out - x).max() <= SCALE


def test_delta_is_smaller_than_keyframe():
    rng = np.random.default_rng(2)
    a = rng.uniform(-2, 2, 16384).astype(np.float32)
    b = a.copy()
    b[:100] += 0.5
    enc = Encoder(a.size)
    key = len(enc.encode(a, POSE))
    assert len(enc.encode(b, POSE)) < key / 5


def test_wide_gaps_roundtrip():
    x = np.zeros(200_000, dtype=np.float32)
    x[5] = 1.0
    x[150_000] = -1.0  # gap > 65535 forces u32 gaps
    enc, rec = Encoder(x.size), Reconstructor(x.size)
    assert np.abs(_roundtrip(enc, rec, x) - x).max() <= SCALE


def test_reset_forces_keyframe():
    a = np.ones(64, dtype=np.float32)
    enc = Encoder(64)
    enc.encode(a, POSE)
    enc.reset()
    assert decode(enc.encode(a, POSE)).keyframe


def test_gap_requires_keyframe():
    a = np.zeros(64, dtype=np.float32)
    enc, rec = Encoder(64), Reconstructor(64)
    _roundtrip(enc, rec, a)
    enc.encode(a, POSE)  # lost packet
    with pytest.raises(ValueError):
        rec.apply(decode(enc.encode(a, POSE)))


def test_bad_input():
    with pytest.raises(ValueError):
        decode(b"\x00" * 40)
    with pytest.raises(ValueError):
        Encoder(4).encode(np.zeros(5, dtype=np.float32), POSE)
    with pytest.raises(ValueError):
        Encoder(4).encode(np.zeros(4, dtype=np.float32), (0, 0))


def test_streamer_end_to_end():
    import asyncio
    from server import Streamer, read_packet, W, H, C

    async def run():
        st = Streamer(fps=60)
        srv = await asyncio.start_server(st.handle, "127.0.0.1", 0)
        port = srv.sockets[0].getsockname()[1]
        prod = asyncio.create_task(st.produce())
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        rec, frames = Reconstructor(W * H * C), []
        for _ in range(10):
            pkt = decode(await asyncio.wait_for(read_packet(reader), 2))
            frames.append(pkt.frame)
            rec.apply(pkt)
        prod.cancel()
        writer.close()
        srv.close()
        return frames

    frames = asyncio.run(run())
    assert frames == sorted(frames)


def test_hybrid_latency_is_rtt_independent():
    low = simulate(500, rtt_mean=10)[2].avg_latency
    high = simulate(500, rtt_mean=150)[2].avg_latency
    assert abs(low - high) < 0.5
    assert simulate(500, rtt_mean=150)[1].avg_latency > high * 5


def test_simulation_is_reproducible():
    assert simulate(200) == simulate(200)
