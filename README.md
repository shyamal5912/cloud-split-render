# cloud-split-render

Cloud streaming ships finished frames, so every camera move waits a full network round trip. This project splits the renderer instead: the client keeps the camera, proxy geometry and HUD, and the server sends only lighting, which tolerates being a few frames old. In the simulation below, input-to-photon latency drops from 78.5 ms to 12.7 ms on a laptop with a weak integrated GPU.

**[▶ Live demo: drag the RTT slider](https://shyamal5912.github.io/cloud-split-render/)** · [Design notes](docs/architecture.md)

[![tests](https://github.com/shyamal5912/cloud-split-render/actions/workflows/ci.yml/badge.svg)](https://github.com/shyamal5912/cloud-split-render/actions/workflows/ci.yml)
[![license](https://img.shields.io/badge/license-AGPL--3.0-blue)](LICENSE)

## How it works

```
        CLIENT (weak iGPU, ~525 MB VRAM, ~6 ms GPU/frame)           SERVER (big GPU)
        ──────────────────────────────────────────────────        ───────────────────────
 input ─► poll + predict pose ──── pose + input (uplink) ─────────► world simulation
              │                                                          │
              ▼                                                          ▼
        proxy geometry, depth                                      full G-buffer
        (always current)                                           ray-traced lighting
              │                                                          │
              │            ◄── lighting delta packets (~9 MB/s) ─── delta encode
              ▼                 each tagged with the pose it was
        reproject lighting      rendered for
        onto the *current* pose
              │
              ▼
        tonemap ─► native-res HUD ─► screen
```

Stages are assigned by a small partitioner ([`server/python/partitioner.py`](server/python/partitioner.py)): anything the player feels immediately (input, camera, edges, HUD) stays local if it fits the GPU and VRAM budget; anything expensive and smooth (global illumination, shadows, world simulation) stays on the server.

## Results

Simulated over 500 frames at 38 ms mean RTT with jitter and queueing spikes. Fixed seed; assumptions are in [`simulator.py`](server/python/simulator.py).

![Average input-to-photon latency](docs/latency.svg)

| Configuration | Avg FPS | 1% low FPS | Input-to-photon | p99 | Bandwidth | Client VRAM |
|---|---:|---:|---:|---:|---:|---:|
| Local only, entry-level laptop | 7.5 | 3.9 | 219.5 ms | 390.8 ms | 0 | 1850 MB |
| Standard video streaming | 57.2 | 20.2 | 78.5 ms | 93.6 ms | 18.5 Mbps | 320 MB |
| **Hybrid split rendering** | **59.9** | **50.0** | **12.7 ms** | **13.6 ms** | **9.4 Mbps** | 525 MB |
| Local only, high-end desktop | 113.8 | 94.6 | 19.2 ms | 20.3 ms | 0 | 11400 MB |

The hybrid number does not depend on RTT, because camera and HUD never wait on the network. What does grow with RTT is the *age of the lighting*. The demo shows it as "lighting age", and a test pins the claim down (`test_hybrid_latency_is_rtt_independent`).

> **These are model outputs, not hardware measurements.** The bandwidth, PSNR-style and memory columns are inputs to the model. Nothing here has been profiled on a real GPU. Treat the shape of the result as the claim, not the exact milliseconds.

## Quickstart

Simulator and tests (Python 3.10+):

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
python server/python/simulator.py          # prints the plan + table, rewrites benchmarks/ and docs/latency.svg
python server/python/simulator.py --rtt 120 --frames 2000
pytest -q
```

Browser demo (no build step; Three.js loads from a CDN):

```bash
python -m http.server 8000 --directory client
# open http://localhost:8000
```

Left pane: whole frames arrive late, drop under load and smear when the camera moves fast. Right pane: same scene, camera and wireframe proxy are instant; only the lights lag. Drag to look, WASD to move, or leave it alone for an automatic whip-pan.

## Layout

```
client/       browser demo: Three.js scene, camera pose history, GLSL shaders
server/
  python/     stage partitioner and latency simulator
  streaming/  delta-packet codec for the lighting stream
benchmarks/   summary.csv written by the simulator
docs/         design notes
tests/        partitioner, codec and simulator tests
```

## Known limits

- The demo fakes the server: lights are animated by a function and delayed by the slider, not streamed from a real renderer.
- The codec is sparse int8 deltas plus zlib. It has no loss recovery beyond "request a keyframe".
- Reprojection of lighting onto a new pose will smear at disocclusions during fast pans. Handling that well (depth-aware warp with a fill pass) is the main open piece.

Licensed under AGPL-3.0.