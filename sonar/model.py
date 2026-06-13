"""Shared dataclasses used by the backends, hints engine, and UI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class StaticInfo:
    """Machine facts sampled once at startup."""

    backend: str                      # "apple" | "nvidia"
    gpu_name: str
    cores: Optional[int] = None       # Apple GPU core count
    gpu_count: int = 1
    mem_total: Optional[int] = None   # unified RAM (Apple) or VRAM (NVIDIA), bytes
    platform: str = ""


@dataclass
class GpuStats:
    """One GPU reading."""

    device_util: float = 0.0
    renderer_util: Optional[float] = None  # Apple only
    tiler_util: Optional[float] = None     # Apple only
    mem_used: Optional[int] = None
    mem_total: Optional[int] = None
    power_w: Optional[float] = None
    temp_c: Optional[float] = None


@dataclass
class ProcInfo:
    """A compute process and the project folder it runs from."""

    pid: int
    name: str
    cmd: str
    cpu: float = 0.0
    mem_pct: float = 0.0
    rss: int = 0
    etime: str = ""
    cwd: Optional[str] = None
    project: Optional[str] = None
    gpu_mem: Optional[int] = None     # real on NVIDIA, None on Apple
    is_gpu: bool = False              # confirmed on NVIDIA, heuristic on Apple


@dataclass
class Hint:
    severity: str  # info | warn | crit
    text: str
