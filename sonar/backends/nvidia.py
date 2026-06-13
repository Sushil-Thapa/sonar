"""NVIDIA backend: everything from nvidia-smi CSV queries (no sudo needed).

Unlike macOS, NVIDIA exposes real per-process GPU memory via
`--query-compute-apps`, so the process table here is ground truth rather than a
heuristic. Multiple GPUs are aggregated (util averaged, memory summed).
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional

from ..model import GpuStats, ProcInfo, StaticInfo
from ..util import project_from_cwd, run
from .base import Backend

_MB = 1024 * 1024


def _fnum(s: str) -> Optional[float]:
    s = s.strip()
    try:
        return float(s)
    except ValueError:
        return None


def parse_query_gpu(text: str) -> StaticInfo:
    """Parse `--query-gpu=name,memory.total` into StaticInfo."""
    names: List[str] = []
    total = 0
    for line in text.strip().splitlines():
        parts = [x.strip() for x in line.split(",")]
        if len(parts) >= 2:
            names.append(parts[0])
            mt = _fnum(parts[1])
            if mt:
                total += int(mt) * _MB
    return StaticInfo(
        backend="nvidia",
        gpu_name=names[0] if names else "NVIDIA GPU",
        gpu_count=len(names) or 1,
        mem_total=total or None,
        platform="Linux",
    )


def parse_sample(text: str) -> GpuStats:
    """Parse `--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw`."""
    utils: List[float] = []
    used = total = 0
    temps: List[float] = []
    powers: List[float] = []
    for line in text.strip().splitlines():
        parts = [x.strip() for x in line.split(",")]
        if len(parts) < 3:
            continue
        u, mu, mt = _fnum(parts[0]), _fnum(parts[1]), _fnum(parts[2])
        if u is not None:
            utils.append(u)
        if mu:
            used += int(mu) * _MB
        if mt:
            total += int(mt) * _MB
        if len(parts) > 3 and _fnum(parts[3]) is not None:
            temps.append(_fnum(parts[3]))
        if len(parts) > 4 and _fnum(parts[4]) is not None:
            powers.append(_fnum(parts[4]))
    return GpuStats(
        device_util=sum(utils) / len(utils) if utils else 0.0,
        mem_used=used or None,
        mem_total=total or None,
        temp_c=max(temps) if temps else None,
        power_w=sum(powers) if powers else None,
    )


def parse_compute_apps(text: str) -> Dict[int, int]:
    """Parse `--query-compute-apps=pid,used_memory` into {pid: gpu_mem_bytes}."""
    out: Dict[int, int] = {}
    for line in text.strip().splitlines():
        parts = [x.strip() for x in line.split(",")]
        if len(parts) >= 2:
            try:
                out[int(parts[0])] = int(float(parts[1])) * _MB
            except ValueError:
                continue
    return out


class NvidiaBackend(Backend):
    name = "nvidia"

    def __init__(self):
        self._static: Optional[StaticInfo] = None
        self._cwd_cache: Dict[int, Optional[str]] = {}

    def static_info(self) -> StaticInfo:
        if self._static:
            return self._static
        self._static = parse_query_gpu(
            run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"])
        )
        return self._static

    def sample(self) -> GpuStats:
        return parse_sample(
            run([
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
                "--format=csv,noheader,nounits",
            ])
        )

    def processes(self, cpu_threshold: float = 20.0) -> List[ProcInfo]:
        gpu_mem = parse_compute_apps(
            run(["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"])
        )
        procs: List[ProcInfo] = []
        for pid, gm in gpu_mem.items():
            cpu = mem = 0.0
            rss = 0
            etime = comm = ""
            line = run(["ps", "-o", "%cpu=,%mem=,rss=,etime=,comm=", "-p", str(pid)]).strip()
            if line:
                parts = line.split(None, 4)
                if len(parts) >= 5:
                    try:
                        cpu, mem, rss = float(parts[0]), float(parts[1]), int(parts[2]) * 1024
                    except ValueError:
                        pass
                    etime, comm = parts[3], parts[4]
            cwd = self._cwd(pid)
            procs.append(
                ProcInfo(
                    pid=pid,
                    name=os.path.basename(comm) or str(pid),
                    cmd=comm,
                    cpu=cpu,
                    mem_pct=mem,
                    rss=rss,
                    etime=etime,
                    cwd=cwd,
                    project=project_from_cwd(cwd),
                    gpu_mem=gm,
                    is_gpu=True,
                )
            )
        procs.sort(key=lambda p: (p.gpu_mem or 0), reverse=True)
        return procs[:12]

    def _cwd(self, pid: int) -> Optional[str]:
        if pid in self._cwd_cache:
            return self._cwd_cache[pid]
        try:
            cwd = os.readlink(f"/proc/{pid}/cwd")
        except OSError:
            cwd = None
        self._cwd_cache[pid] = cwd
        return cwd
