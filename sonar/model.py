"""Plain data containers shared across backends, hints, and UI.

Keeping these as dumb dataclasses means parsers, the hints engine, and the
renderer all speak the same vocabulary without importing each other.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class StaticInfo:
    """Slow-changing facts about the machine, sampled once at startup."""

    backend: str                      # "apple" | "nvidia"
    gpu_name: str
    cores: Optional[int] = None       # Apple GPU core count
    gpu_count: int = 1                # number of discrete GPUs (NVIDIA)
    mem_total: Optional[int] = None   # bytes (unified RAM on Apple, VRAM on NVIDIA)
    platform: str = ""


@dataclass
class GpuStats:
    """One instantaneous reading of GPU utilization and memory."""

    device_util: float = 0.0          # 0-100, the headline number
    renderer_util: Optional[float] = None  # Apple only
    tiler_util: Optional[float] = None     # Apple only
    mem_used: Optional[int] = None    # bytes
    mem_total: Optional[int] = None   # bytes
    power_w: Optional[float] = None   # NVIDIA, or Apple w/ --power
    temp_c: Optional[float] = None    # NVIDIA


@dataclass
class ProcInfo:
    """A candidate compute process and the project folder it runs from."""

    pid: int
    name: str
    cmd: str
    cpu: float = 0.0
    mem_pct: float = 0.0
    rss: int = 0                      # bytes
    etime: str = ""                   # elapsed time, ps format
    cwd: Optional[str] = None
    project: Optional[str] = None
    gpu_mem: Optional[int] = None     # bytes, real on NVIDIA, None on Apple
    is_gpu: bool = False              # confirmed (NVIDIA) or heuristic (Apple)


@dataclass
class Hint:
    """An optimization/health observation. severity: info | warn | crit."""

    severity: str
    text: str
