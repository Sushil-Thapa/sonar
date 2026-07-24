"""Apple Silicon backend: GPU stats from ioreg, processes from ps + lsof.

macOS exposes no public per-process GPU API, so the strategy is:
  * read the *global* GPU utilization/memory from IOAccelerator (no sudo), and
  * surface the heavy compute processes and the project folder each runs from,
    attributing the global number to the dominant run.
This is accurate for serial single-GPU workflows (one training run at a time).
"""

from __future__ import annotations

import os
import re
from typing import Dict, List, Optional

from ..model import GpuStats, ProcInfo, StaticInfo
from ..util import exe_basename, project_from_cwd, run, short_command
from .base import Backend

# Executable names and command-line markers that suggest a GPU workload.
#
# macOS does not expose public per-process GPU use, so this intentionally
# avoids a generic "hot CPU process" fallback. The process table should answer
# "which training/model run is likely responsible?" rather than becoming htop.
_GPU_EXE = re.compile(
    r"^(python\d*(?:\.\d+)?|pypy\d*|ipython|jupyter.*|mlx.*|ollama|llama.*|ggml.*|"
    r"comfy.*|stable.*|mojo|julia)$",
    re.I,
)
_GPU_CMD = re.compile(
    r"(^|[/\s._-])("
    r"mlx|ollama|llama|llava|qwen|mistral|gemma|deepseek|"
    r"torch|tensorflow|transformers|jax|vllm|accelerate|deepspeed|"
    r"comfyui|stable-diffusion|grpo|lora|finetun(?:e|ing)|train|eval"
    r")([/\s._-]|$)",
    re.I,
)
_PYTHON_EXE = re.compile(r"^(python\d*(?:\.\d+)?|pypy\d*)$", re.I)
_ASSISTANT_EXE = re.compile(r"^(claude|codex|chatgpt)$", re.I)


def _is_sonar_monitor(args: str) -> bool:
    toks = args.split()
    if not toks:
        return False
    names = [os.path.basename(t) for t in toks]
    if names[0] == "sonar":
        return True
    if len(names) >= 3 and names[0] == "uv" and names[1] == "run" and names[2] == "sonar":
        return True
    if len(names) >= 2 and _PYTHON_EXE.fullmatch(names[0]) and names[1] == "sonar":
        return True
    return False


def parse_ioreg(text: str) -> Dict[str, int]:
    """Pull the IOAccelerator PerformanceStatistics dict out of ioreg output.

    There can be several IOAccelerator nodes; we prefer the block that actually
    reports "Device Utilization %" (the real GPU), falling back to the first.
    """
    best: Dict[str, int] = {}
    for block in re.findall(r'"PerformanceStatistics"\s*=\s*\{([^}]*)\}', text):
        d = {k: int(v) for k, v in re.findall(r'"([^"]+)"=(-?\d+)', block)}
        if "Device Utilization %" in d:
            return d
        if not best:
            best = d
    return best


def parse_gpu_power(text: str) -> Optional[float]:
    """Extract GPU power in watts from `powermetrics --samplers gpu_power`."""
    m = re.search(r"GPU Power:\s*([\d.]+)\s*mW", text)
    return float(m.group(1)) / 1000.0 if m else None


def parse_displays(text: str):
    """Extract (gpu_name, core_count) from `system_profiler SPDisplaysDataType`."""
    name = ""
    cores: Optional[int] = None
    m = re.search(r"Chipset Model:\s*(.+)", text)
    if m:
        name = m.group(1).strip()
    m = re.search(r"Total Number of Cores:\s*(\d+)", text)
    if m:
        cores = int(m.group(1))
    return name, cores


def parse_ps(text: str, exclude_pid: int = -1, cpu_threshold: float = 20.0):
    """Turn `ps -axo pid=,%cpu=,%mem=,rss=,etime=,args=` lines into ProcInfo.

    Matching uses the executable basename (precise); the displayed command is
    the full, shortened argument line so you see the actual script/config.
    Keep only likely GPU work: Python/ML runtimes or commands carrying
    training/model markers. Assistant shells like Claude/Codex/ChatGPT are
    intentionally excluded because they are usually orchestration/UI noise; if
    they launch a GPU job, the Python/model child process is what should show.
    cwd/project are filled in later.
    """
    procs: List[ProcInfo] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 5)
        if len(parts) < 6:
            continue
        pid_s, cpu_s, mem_s, rss_s, etime, args = parts
        try:
            pid = int(pid_s)
            cpu = float(cpu_s)
            mem = float(mem_s)
            rss = int(rss_s) * 1024
        except ValueError:
            continue
        if pid == exclude_pid:
            continue
        name = exe_basename(args)
        if _is_sonar_monitor(args):
            continue
        if _ASSISTANT_EXE.fullmatch(name):
            continue
        is_candidate = bool(_GPU_EXE.search(name) or _GPU_CMD.search(args))
        # Candidates need a small CPU floor to drop idle helpers. Do not fall
        # back to generic high-CPU processes; they swamp the useful AI list.
        if not is_candidate or cpu < 1.0:
            continue
        procs.append(
            ProcInfo(
                pid=pid,
                name=name,
                cmd=short_command(args),
                cpu=cpu,
                mem_pct=mem,
                rss=rss,
                etime=etime,
                is_gpu=is_candidate,
            )
        )
    return procs


class AppleBackend(Backend):
    name = "apple"

    def __init__(self, power: bool = False):
        self._static: Optional[StaticInfo] = None
        self._cwd_cache: Dict[int, Optional[str]] = {}
        self.power = power               # opt-in GPU wattage (sudo); see _gpu_power
        self._last_power: Optional[float] = None

    def static_info(self) -> StaticInfo:
        if self._static:
            return self._static
        name, cores = parse_displays(run(["system_profiler", "SPDisplaysDataType"], timeout=8))
        mem = run(["sysctl", "-n", "hw.memsize"]).strip()
        self._static = StaticInfo(
            backend="apple",
            gpu_name=name or "Apple GPU",
            cores=cores,
            mem_total=int(mem) if mem.isdigit() else None,
            platform="macOS",
        )
        return self._static

    def sample(self) -> GpuStats:
        d = parse_ioreg(run(["ioreg", "-r", "-c", "IOAccelerator", "-d", "1"], timeout=4))
        return GpuStats(
            device_util=float(d.get("Device Utilization %", 0)),
            renderer_util=float(d["Renderer Utilization %"]) if "Renderer Utilization %" in d else None,
            tiler_util=float(d["Tiler Utilization %"]) if "Tiler Utilization %" in d else None,
            mem_used=d.get("In use system memory"),
            mem_total=self.static_info().mem_total,
            power_w=self._gpu_power() if self.power else None,
        )

    def _gpu_power(self) -> Optional[float]:
        """GPU wattage via `sudo -n powermetrics`. Needs passwordless sudo.

        Non-interactive (`-n`) so it never blocks the TUI on a password prompt;
        if sudo isn't pre-authorized it yields nothing and we keep the last
        known value (or None).
        """
        out = run(
            ["sudo", "-n", "powermetrics", "--samplers", "gpu_power", "-n1", "-i", "200"],
            timeout=5,
        )
        w = parse_gpu_power(out)
        if w is not None:
            self._last_power = w
        return self._last_power

    def processes(self, cpu_threshold: float = 20.0) -> List[ProcInfo]:
        text = run(["ps", "-axo", "pid=,%cpu=,%mem=,rss=,etime=,args="], timeout=4)
        procs = parse_ps(text, exclude_pid=os.getpid(), cpu_threshold=cpu_threshold)
        for p in procs:
            p.cwd = self._cwd(p.pid)
            p.project = project_from_cwd(p.cwd)
        procs.sort(key=lambda p: p.cpu, reverse=True)
        return procs[:12]

    def _cwd(self, pid: int) -> Optional[str]:
        """Resolve a PID's working directory via lsof (cached; cwd is stable)."""
        if pid in self._cwd_cache:
            return self._cwd_cache[pid]
        out = run(["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"], timeout=3)
        cwd = None
        for line in out.splitlines():
            if line.startswith("n"):
                cwd = line[1:]
                break
        self._cwd_cache[pid] = cwd
        return cwd
