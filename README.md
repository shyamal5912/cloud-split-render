# cloud-split-render

Cloud streaming ships finished frames, so every camera move waits a full network round trip. This project splits the renderer instead: the client keeps the camera, proxy geometry and HUD, and the server sends only lighting, which tolerates being a few frames old. Camera latency then stops depending on the network. This is a prototype: the codec and partitioner are real and measured below, but end-to-end latency has not been measured on real hardware.

**[▶ Live demo: drag the RTT slider](https://shyamal5912.github.io/cloud-split-render/)** · [Design notes](docs/architecture.md)

[![tests](https://github.com/shyamal5912/cloud-split-render/actions/workflows/ci.yml/badge.svg)](https://github.com/shyamal5912/cloud-split-render/actions/workflows/ci.yml)
[![license](https://img.shields.io/badge/license-AGPL--3.0-blue)](LICENSE)

## How it works

```
        CLIENT (weak iGPU)                                           SERVER (big GPU)
        ──────────────────────────────────────────────────        ───────────────────────
 input ─► poll + predict pose ──── pose + input (uplink) ─────────► world simulation
              │                                                          │
              ▼                                                          ▼
        proxy geometry, depth                                      full G-buffer
        (always current)                                           ray-traced lighting
              │                                                          │
              │            ◄── lighting delta packets ─── delta encode
              ▼                 each tagged with the pose it was
        reproject lighting      rendered for
        onto the *current* pose
              │
              ▼
        tonemap ─► native-res HUD ─► screen
```

Stages are assigned by a small partitioner ([`server/python/partitioner.py`](server/python/partitioner.py)): anything the player feels immediately (input, camera, edges, HUD) stays local if it fits the GPU and VRAM budget; anything expensive and smooth (global illumination, shadows, world simulation) stays on the server.

## Measured results

What has actually been measured is the lighting delta codec, on the CPU of the machine that ran [`benchmarks/codec_bench.py`](benchmarks/codec_bench.py) (2 vCPU cloud VM, Python + numpy, synthetic data). Lighting buffer 320×180×3 = 172,800 cells; a full keyframe is 432 KiB.

| Cells changed per frame | Packet size | Bandwidth at 60 fps | Encode | Decode |
|---:|---:|---:|---:|---:|
| 1% | 4.2 KiB | 2.1 Mbps | 0.80 ms | 0.19 ms |
| 5% | 18.0 KiB | 8.8 Mbps | 1.37 ms | 0.38 ms |
| 20% | 68.4 KiB | 33.6 Mbps | 3.53 ms | 1.17 ms |
| 50% | 169.6 KiB | 83.4 Mbps | 7.96 ms | 2.64 ms |

Takeaway: sparse deltas stay small only while little of the lighting changes per frame. The real bandwidth of a game depends on how much of its lighting changes, which this repo does not yet measure.

## Latency model (not a measurement)

[`server/python/simulator.py`](server/python/simulator.py) is a per-frame model of four setups that adds up assumed costs (input, network, encode, decode, scanout). Its output only reflects those assumptions, so it is not reported here as a result. Run it with your own RTT and costs: `python server/python/simulator.py --rtt 80`. The live demo shows the same model, so its on-screen millisecond readouts are modelled values too; the lag and smear you can see in the panes are real rendering effects, applied with the slider's delay.

## Quickstart

Simulator and tests (Python 3.10+):

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
python server/python/simulator.py          # prints the plan + modelled table
python benchmarks/codec_bench.py           # measured codec timings
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
benchmarks/   codec benchmark, plus modelled summary.csv
docs/         design notes
tests/        partitioner, codec and simulator tests
```


Licensed under AGPL-3.0.