"""Measures the delta codec on this machine. Real timings, synthetic input.

    python benchmarks/codec_bench.py
"""
import statistics as st
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server" / "streaming"))
from delta_packets import Reconstructor, SCALE, decode, encode  # noqa: E402

POSE = (0, 1, 2, 0, 0, 0, 1)
W, H, C = 320, 180, 3  # lighting buffer resolution
N = W * H * C
rng = np.random.default_rng(0)


def bench(changed_fraction: float, frames: int = 120):
    buf = rng.uniform(-2, 2, N).astype(np.float32)
    rec = Reconstructor(N)
    rec.apply(decode(encode(0, buf, None, POSE), N))
    enc, dec, sizes, err = [], [], [], 0.0
    for f in range(1, frames + 1):
        mask = rng.random(N) < changed_fraction
        nxt = buf + (rng.normal(0, 0.1, N) * mask).astype(np.float32)
        t = time.perf_counter(); data = encode(f, nxt, buf, POSE); enc.append(time.perf_counter() - t)
        t = time.perf_counter(); out = rec.apply(decode(data, N)); dec.append(time.perf_counter() - t)
        sizes.append(len(data)); err = max(err, float(np.abs(out - nxt).max()))
        buf = nxt
    return st.mean(sizes), st.mean(enc) * 1e3, st.mean(dec) * 1e3, err


key = len(encode(0, rng.uniform(-2, 2, N).astype(np.float32), None, POSE))
print(f"buffer {W}x{H}x{C} = {N} cells, keyframe {key/1024:.1f} KiB\n")
print("| Cells changed per frame | Packet | Mbps at 60 fps | Encode | Decode | Max drift |")
print("|---:|---:|---:|---:|---:|---:|")
for frac in (0.01, 0.05, 0.20, 0.50):
    size, e, d, err = bench(frac)
    print(f"| {frac:.0%} | {size/1024:.1f} KiB | {size*8*60/1e6:.1f} | {e:.2f} ms | {d:.2f} ms | {err:.3f} |")
