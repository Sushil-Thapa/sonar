"""Rule-based optimization/health hints over the current sample + recent history.

Pure function: feed it the latest stats, processes, and the util ring buffer,
get back a list of Hints. No I/O, so it's trivial to unit test.
"""

from __future__ import annotations

from typing import Iterable, List

from .model import GpuStats, Hint, ProcInfo, StaticInfo

_IDLE = 5.0          # below this, the GPU is effectively idle
_UNDERUSED = 30.0    # sustained util below this during a run is wasteful
_RECENT = 8          # samples considered "recent" for trend rules
_ACTIVE_CPU = 25.0   # CPU% above which a process counts as a genuinely active run


def _is_active_run(p) -> bool:
    """A real workload, not an idle candidate (e.g. a parked Jupyter kernel).

    True if it holds GPU memory (NVIDIA, ground truth) or is burning CPU
    (the proxy on macOS, where per-process GPU use is unobservable).
    """
    return bool(p.gpu_mem) or p.cpu >= _ACTIVE_CPU


def evaluate(
    static: StaticInfo,
    stats: GpuStats,
    procs: List[ProcInfo],
    util_history: Iterable[float],
) -> List[Hint]:
    hints: List[Hint] = []
    gpu_procs = [p for p in procs if p.is_gpu]
    recent = list(util_history)[-_RECENT:]

    # Memory pressure (close to the unified-RAM / VRAM ceiling).
    if stats.mem_used and stats.mem_total:
        frac = stats.mem_used / stats.mem_total
        if frac > 0.9:
            hints.append(Hint("crit", f"GPU memory at {frac * 100:.0f}% of total — OOM/swap risk"))
        elif frac > 0.8:
            hints.append(Hint("warn", f"GPU memory at {frac * 100:.0f}% of total — limited headroom"))

    # Co-resident runs (violates a serial single-GPU policy). Only count
    # genuinely active runs so an idle kernel next to a real run doesn't trip it.
    active = [p for p in gpu_procs if _is_active_run(p)]
    if len(active) >= 2:
        who = ", ".join(sorted({p.project or p.name for p in active}))
        hints.append(Hint("warn", f"{len(active)} active runs co-resident ({who}) — expected one at a time"))

    # Live run but the GPU is idle: stall or input-pipeline bound.
    if gpu_procs and len(recent) >= 5 and all(u < _IDLE for u in recent):
        hints.append(Hint("warn", "GPU idle while a compute process is alive — possible stall or data-loading bottleneck"))

    # Run present but chronically underutilized.
    elif gpu_procs and len(recent) >= 5:
        avg = sum(recent) / len(recent)
        if _IDLE <= avg < _UNDERUSED:
            hints.append(Hint("info", f"GPU averaging {avg:.0f}% during a run — underutilized (batch size / input pipeline?)"))

    # Load with nobody attributed.
    if stats.device_util > 50 and not gpu_procs:
        hints.append(Hint("info", f"GPU at {stats.device_util:.0f}% but no compute process attributed (try lowering --cpu-threshold)"))

    if not hints:
        hints.append(Hint("info", "Nothing notable — GPU healthy."))
    return hints
