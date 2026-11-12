import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "server" / "python"), str(ROOT / "server" / "streaming")]

from delta_packets import Reconstructor, SCALE, decode, encode  # noqa: E402
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


def test_codec_roundtrip():
    rng = np.random.default_rng(1)
    a = rng.uniform(-2, 2, 4096).astype(np.float32)
    b = a + rng.normal(0, 0.05, a.shape).astype(np.float32) * (rng.random(4096) < 0.1)
    rec = Reconstructor(a.size)
    out = rec.apply(decode(encode(0, a, None, POSE), a.size))
    assert np.abs(out - a).max() <= SCALE
    out = rec.apply(decode(encode(1, b, a, POSE), a.size))
    assert np.abs(out - b).max() <= 2 * SCALE


def test_delta_is_smaller_than_keyframe():
    rng = np.random.default_rng(2)
    a = rng.uniform(-2, 2, 16384).astype(np.float32)
    b = a.copy()
    b[:100] += 0.5
    assert len(encode(1, b, a, POSE)) < len(encode(0, a, None, POSE)) / 5


def test_gap_requires_keyframe():
    a = np.zeros(64, dtype=np.float32)
    rec = Reconstructor(64)
    rec.apply(decode(encode(0, a, None, POSE), 64))
    with pytest.raises(ValueError):
        rec.apply(decode(encode(5, a, a, POSE), 64))


def test_bad_magic():
    with pytest.raises(ValueError):
        decode(b"\x00" * 40, 4)


def test_hybrid_latency_is_rtt_independent():
    low = simulate(500, rtt_mean=10)[2].avg_latency
    high = simulate(500, rtt_mean=150)[2].avg_latency
    assert abs(low - high) < 0.5
    assert simulate(500, rtt_mean=150)[1].avg_latency > high * 5


def test_simulation_is_reproducible():
    assert simulate(200) == simulate(200)
