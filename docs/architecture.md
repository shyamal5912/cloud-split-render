# Design notes

## Two axes per stage

Every stage of a frame is scored on:

- **Latency sensitivity**: how much it affects the feel of input. Input polling, camera update and HUD score near 1.0.
- **Sharpness**: how badly video compression damages its output. Geometry edges and text score high; soft lighting scores low.

Expensive stages (global illumination, shadow cascades, world simulation) are low on both, so they can run remotely and arrive late without the player noticing. Cheap, high-scoring stages run locally. On the reference pipeline that means 6 of 11 stages stay on the client and cost about 6 ms of GPU time per frame and 525 MB of VRAM.

## Placement rule

For stages sorted by descending sensitivity, a stage goes to the client if all hold:

1. it has a local variant (and the hardware it needs, e.g. ray-tracing),
2. sensitivity ≥ 0.80,
3. it fits both the remaining GPU-time budget (40% of a 60 fps frame by default) and the VRAM budget.

Otherwise a stage that can be predicted locally and corrected by the server is `split` (costed at 5% of the full stage), and everything else is `server`.

## Latency model

Streaming: `input 3.5 + RTT + encode 12 + decode 8 + scanout 14` ms.

Hybrid: `input 1 + pose update 1.4 + local GPU + half-frame scanout`, with no RTT term. The lighting buffer has age `RTT + server render + encode`, which is the price paid.

## Packet format

See the docstring in [`server/streaming/delta_packets.py`](../server/streaming/delta_packets.py). Each packet carries the camera pose it was rendered for so the client can reproject onto its newer pose. A gap in frame numbers forces a keyframe.

## What is not modelled

Packet loss, congestion control and encoder queueing under load. The browser demo does implement depth-based reprojection with disocclusion discard and blur fill, but it has no quality metric; judge it by eye. Each can be added to `simulate()` as another per-frame term.
