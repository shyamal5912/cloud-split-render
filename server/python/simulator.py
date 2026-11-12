"""Frame-by-frame latency simulation of four ways to run the same heavy workload.

This is a model, not a measurement: every constant below is an explicit
assumption and can be changed. Fixed seed, so runs are reproducible.

    python server/python/simulator.py            # print table, write CSVs and chart
    python server/python/simulator.py --frames 2000 --rtt 80
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from partitioner import BASIC_LAPTOP, Partitioner

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Result:
    name: str
    avg_fps: float
    low1_fps: float
    avg_latency: float
    p99_latency: float
    lighting_age: float
    psnr_db: float
    ram_mb: int
    vram_mb: int
    bandwidth_mbps: float


def _rtt(rng: np.random.Generator, n: int, mean: float, jitter: float) -> np.ndarray:
    # Gaussian base plus an exponential tail for queueing spikes.
    return np.clip(rng.normal(mean, jitter, n) + rng.exponential(3.0, n), 1.0, None)


def simulate(frames: int = 500, rtt_mean: float = 38.0, seed: int = 42) -> list[Result]:
    rng = np.random.default_rng(seed)
    rtt = _rtt(rng, frames, rtt_mean, 6.0)

    # 1. Everything local on a weak iGPU: memory thrashing, long frames.
    ft_local = rng.normal(115.0, 22.0, frames).clip(40) + rng.exponential(25.0, frames)
    lat_local = ft_local * 1.45 + 15.5

    # 2. Video streaming: input + network + encode + decode + scanout.
    hitch = np.where(rng.random(frames) < 0.08, rng.uniform(12, 35, frames), 0)
    ft_stream = np.clip(rng.normal(16.67, 1.8, frames) + hitch, 14.0, 65.0)
    lat_stream = 3.5 + rtt + 12.0 + 8.0 + 14.0

    # 3. Hybrid: camera and HUD are local, so latency does not depend on RTT.
    # Pose update 1.4 + proxy/warp pass 5.4 + half a frame of scanout + input.
    plan = Partitioner(BASIC_LAPTOP).plan()
    local_ms = Partitioner.totals(plan)["client_gpu_ms"]
    ft_hybrid = rng.normal(16.67, 0.65, frames) + np.where(
        rng.random(frames) < 0.02, rng.uniform(2, 5, frames), 0)
    lat_hybrid = 1.0 + 1.4 + local_ms + 16.67 / 2 * 0.5 + rng.normal(0, 0.4, frames)
    # What does depend on RTT is how old the server-side lighting is.
    light_age = rtt + 7.5 + 4.0  # uplink+downlink, server render, delta encode

    # 4. Reference high-end local machine.
    ft_high = rng.normal(8.8, 0.7, frames).clip(5)
    lat_high = 19.2 + rng.normal(0, 0.5, frames)

    rows = [
        ("Local only (entry-level laptop)", ft_local, lat_local, 0.0, 24.5, 3920, 1850, 0.0),
        ("Standard video streaming", ft_stream, lat_stream, 0.0, 31.8, 1150, 320, 18.5),
        ("Hybrid split rendering", ft_hybrid, lat_hybrid, float(light_age.mean()),
         41.2, 1820, int(Partitioner.totals(plan)["client_vram_mb"]), 9.4),
        ("Local only (high-end desktop)", ft_high, lat_high, 0.0, 48.0, 14800, 11400, 0.0),
    ]
    out = []
    for name, ft, lat, age, psnr, ram, vram, bw in rows:
        fps = 1000.0 / ft
        out.append(Result(
            name, round(float(fps.mean()), 1), round(float(np.percentile(fps, 1)), 1),
            round(float(lat.mean()), 1), round(float(np.percentile(lat, 99)), 1),
            round(age, 1), psnr, ram, vram, bw))
    return out


def write_csv(results: list[Result], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["config", "avg_fps", "p1_low_fps", "avg_latency_ms", "p99_latency_ms",
                    "lighting_age_ms", "psnr_db", "client_ram_mb", "client_vram_mb",
                    "bandwidth_mbps"])
        for r in results:
            w.writerow([r.name, r.avg_fps, r.low1_fps, r.avg_latency, r.p99_latency,
                        r.lighting_age, r.psnr_db, r.ram_mb, r.vram_mb, r.bandwidth_mbps])


def markdown_table(results: list[Result]) -> str:
    head = ("| Configuration | Avg FPS | 1% low FPS | Input-to-photon (ms) | p99 (ms) "
            "| Bandwidth (Mbps) | Client VRAM (MB) |\n|---|---:|---:|---:|---:|---:|---:|\n")
    return head + "\n".join(
        f"| {r.name} | {r.avg_fps} | {r.low1_fps} | {r.avg_latency} | {r.p99_latency} "
        f"| {r.bandwidth_mbps} | {r.vram_mb} |" for r in results)


def write_svg(results: list[Result], path: Path) -> None:
    """Dependency-free horizontal bar chart of average input-to-photon latency."""
    colors = ["#8b949e", "#f0883e", "#3fb950", "#58a6ff"]
    w, bar_h, gap, left, top = 760, 34, 22, 250, 70
    peak = max(r.avg_latency for r in results)
    h = top + len(results) * (bar_h + gap) + 30
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" font-family="Segoe UI,Helvetica,Arial,sans-serif">',
        f'<rect width="{w}" height="{h}" rx="12" fill="#0d1117"/>',
        '<text x="24" y="36" fill="#e6edf3" font-size="18" font-weight="600">'
        'Average input-to-photon latency (lower is better)</text>',
        '<text x="24" y="55" fill="#8b949e" font-size="12">Simulated, 500 frames, '
        'entry-level client unless noted</text>',
    ]
    for i, (r, c) in enumerate(zip(results, colors)):
        y = top + i * (bar_h + gap)
        bw = (w - left - 90) * r.avg_latency / peak
        parts += [
            f'<text x="{left - 12}" y="{y + 22}" fill="#e6edf3" font-size="13" '
            f'text-anchor="end">{r.name}</text>',
            f'<rect x="{left}" y="{y}" width="{bw:.1f}" height="{bar_h}" rx="6" fill="{c}"/>',
            f'<text x="{left + bw + 8:.1f}" y="{y + 22}" fill="#e6edf3" font-size="13" '
            f'font-weight="600">{r.avg_latency} ms</text>',
        ]
    parts.append("</svg>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(parts))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--frames", type=int, default=500)
    ap.add_argument("--rtt", type=float, default=38.0, help="mean network RTT in ms")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--no-write", action="store_true", help="print only")
    args = ap.parse_args()

    plan = Partitioner(BASIC_LAPTOP).plan()
    print(f"{'Stage':<42}{'Placement':<9}{'GPU ms':>8}{'VRAM MB':>9}")
    for p in plan:
        print(f"{p.stage.name:<42}{p.tier.value:<9}{p.client_gpu_ms:>8.2f}{p.client_vram_mb:>9}")
    print("totals:", Partitioner.totals(plan), "\n")

    results = simulate(args.frames, args.rtt, args.seed)
    print(markdown_table(results))
    if not args.no_write:
        write_csv(results, ROOT / "benchmarks" / "summary.csv")
        write_svg(results, ROOT / "docs" / "latency.svg")
        print("\nwrote benchmarks/summary.csv and docs/latency.svg")


if __name__ == "__main__":
    main()
