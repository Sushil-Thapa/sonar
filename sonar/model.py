"""Shared dataclasses used by the backends, hints engine, and UI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


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


@dataclass
class GpuqJob:
    """One scheduler/gpuq job for display in the TUI."""

    id: str
    project: str = ""
    name: str = ""
    status: str = ""
    cmd: str = ""
    priority: Optional[int] = None
    workdir: str = ""
    pid: Optional[int] = None
    submitted: Optional[float] = None
    started: Optional[float] = None
    elapsed_seconds: Optional[float] = None
    eta_seconds: Optional[float] = None
    wait_seconds: Optional[float] = None
    progress_current: Optional[int] = None
    progress_total: Optional[int] = None
    progress_label: str = ""


@dataclass
class GpuqSnapshot:
    """Current scheduler/gpuq state.

    unavailable means sonar could not find/read a gpuq home; error is a soft
    parse/read failure and should not break the monitor.
    """

    available: bool = False
    paused: bool = False
    running: Optional[GpuqJob] = None
    queued: List[GpuqJob] = None
    error: str = ""
    updated_at: Optional[float] = None
    remote_hosts: List["RemoteHost"] = None  # remote cluster snapshots, if any

    def __post_init__(self) -> None:
        if self.queued is None:
            self.queued = []
        if self.remote_hosts is None:
            self.remote_hosts = []


@dataclass
class RemoteGpu:
    """One GPU on a remote node, from an out-of-band probe."""

    index: int
    util_pct: float = 0.0
    mem_used_mib: Optional[int] = None
    mem_total_mib: Optional[int] = None
    users: List[str] = None

    def __post_init__(self) -> None:
        if self.users is None:
            self.users = []


@dataclass
class RemoteNode:
    """A remote compute node; unreachable ones carry no GPU readings."""

    name: str
    reachable: bool = False
    gpus: List[RemoteGpu] = None

    def __post_init__(self) -> None:
        if self.gpus is None:
            self.gpus = []


@dataclass
class RemoteAlloc:
    """A scheduler allocation on a remote host (who holds what)."""

    user: str = ""
    node: str = ""
    gres: str = ""
    state: str = ""
    jobname: str = ""
    elapsed: str = ""


@dataclass
class RemoteHost:
    """One remote host snapshot read from <gpuq-home>/remote/<host>.json.

    Every field is optional so old-schema or partial files still render. age is
    computed from ts at read time; stale marks a snapshot older than the reader's
    threshold.
    """

    host: str
    ts: Optional[float] = None
    age_seconds: Optional[float] = None
    stale: bool = False
    disk_usage: Optional[str] = None
    n_jobs: int = 0
    nodes: List[RemoteNode] = None
    allocs: List[RemoteAlloc] = None

    def __post_init__(self) -> None:
        if self.nodes is None:
            self.nodes = []
        if self.allocs is None:
            self.allocs = []
