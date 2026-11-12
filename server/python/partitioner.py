"""Decides which render/simulation stages run on the client and which stay on the server.

A stage stays local only if it is latency sensitive, has a cheap local variant,
and still fits the client's per-frame GPU and VRAM budget. Everything else is
offloaded. Stages are considered in descending order of latency sensitivity, so
when the budget runs out the least responsiveness-critical stages are the ones
that get pushed to the server.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable


class Tier(str, Enum):
    CLIENT = "client"
    SERVER = "server"
    SPLIT = "split"  # client predicts, server is authoritative


@dataclass(frozen=True)
class ClientProfile:
    name: str
    cpu_cores: int
    ram_mb: int
    gpu_tflops: float
    vram_budget_mb: int
    has_hw_raytracing: bool
    rtt_ms: float


@dataclass(frozen=True)
class Stage:
    stage_id: str
    name: str
    latency_sensitivity: float  # 0..1, how much it shapes input-to-photon feel
    sharpness: float            # 0..1, how much video compression would hurt it
    local_gpu_ms: float         # cost of the local (proxy) variant on a weak iGPU
    local_vram_mb: int
    has_local_variant: bool
    needs_hw_raytracing: bool = False
    split_capable: bool = False  # can be predicted locally and corrected by the server


@dataclass(frozen=True)
class Placement:
    stage: Stage
    tier: Tier
    client_gpu_ms: float
    client_vram_mb: int


# Reference pipeline of a modern open-world renderer, described generically.
REFERENCE_PIPELINE: tuple[Stage, ...] = (
    Stage("S1", "Input polling", 1.00, 0.20, 0.01, 10, True),
    Stage("S2", "Player kinematics and pose extrapolation", 0.95, 0.15, 0.04, 25, True,
          split_capable=True),
    Stage("S3", "World simulation (AI, traffic, physics)", 0.40, 0.05, 2.50, 150, False,
          split_capable=True),
    Stage("S4", "Proxy geometry, depth and stencil", 0.92, 0.85, 3.80, 310, True),
    Stage("S5", "Full G-buffer and asset streaming", 0.50, 0.90, 6.50, 5800, False),
    Stage("S6", "Ray-traced GI, AO and reflections", 0.10, 0.10, 65.0, 2100, False,
          needs_hw_raytracing=True),
    Stage("S7", "Shadow cascades and volumetrics", 0.15, 0.10, 18.5, 1200, False),
    Stage("S8", "Water, clouds and planar reflections", 0.20, 0.20, 9.5, 420, False),
    Stage("S9", "Pose warp and irradiance composite", 1.00, 0.80, 1.30, 95, True),
    Stage("S10", "Tonemapping and anti-aliasing", 0.80, 0.70, 0.50, 45, True),
    Stage("S11", "Native-resolution HUD and present", 1.00, 1.00, 0.50, 40, True),
)


class Partitioner:
    def __init__(self, client: ClientProfile, target_fps: int = 60,
                 gpu_load_ratio: float = 0.40, sensitivity_threshold: float = 0.80):
        if not 0 < gpu_load_ratio <= 1:
            raise ValueError("gpu_load_ratio must be in (0, 1]")
        self.client = client
        self.frame_budget_ms = 1000.0 / target_fps
        self.gpu_budget_ms = self.frame_budget_ms * gpu_load_ratio
        self.threshold = sensitivity_threshold

    def plan(self, stages: Iterable[Stage] = REFERENCE_PIPELINE) -> list[Placement]:
        stages = list(stages)
        gpu_used, vram_used = 0.0, 0
        chosen: dict[str, Placement] = {}

        for s in sorted(stages, key=lambda s: s.latency_sensitivity, reverse=True):
            fits = (gpu_used + s.local_gpu_ms <= self.gpu_budget_ms
                    and vram_used + s.local_vram_mb <= self.client.vram_budget_mb)
            runnable = s.has_local_variant and (
                not s.needs_hw_raytracing or self.client.has_hw_raytracing)
            if runnable and s.latency_sensitivity >= self.threshold and fits:
                gpu_used += s.local_gpu_ms
                vram_used += s.local_vram_mb
                chosen[s.stage_id] = Placement(s, Tier.CLIENT, s.local_gpu_ms, s.local_vram_mb)
            elif s.split_capable and s.latency_sensitivity >= self.threshold:
                # Only the cheap predictive half runs here; costed at 5% of the full stage.
                cost, mem = s.local_gpu_ms * 0.05, max(1, s.local_vram_mb // 20)
                gpu_used += cost
                vram_used += mem
                chosen[s.stage_id] = Placement(s, Tier.SPLIT, cost, mem)
            else:
                chosen[s.stage_id] = Placement(s, Tier.SERVER, 0.0, 0)

        return [chosen[s.stage_id] for s in stages]

    @staticmethod
    def totals(plan: Iterable[Placement]) -> dict[str, float]:
        plan = list(plan)
        return {
            "client_gpu_ms": round(sum(p.client_gpu_ms for p in plan), 2),
            "client_vram_mb": sum(p.client_vram_mb for p in plan),
            "local_stages": sum(p.tier is not Tier.SERVER for p in plan),
            "server_stages": sum(p.tier is Tier.SERVER for p in plan),
        }


BASIC_LAPTOP = ClientProfile(
    name="Entry-level laptop (2 cores, integrated GPU)",
    cpu_cores=2, ram_mb=4096, gpu_tflops=0.38, vram_budget_mb=800,
    has_hw_raytracing=False, rtt_ms=38.0,
)
