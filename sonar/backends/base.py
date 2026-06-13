"""The seam between sonar and a specific GPU stack.

A backend answers three questions: what is this machine (static_info), what is
the GPU doing right now (sample), and which processes are driving it
(processes). Everything above this interface is platform-agnostic.
"""

from __future__ import annotations

from typing import List

from ..model import GpuStats, ProcInfo, StaticInfo


class Backend:
    name = "base"

    def static_info(self) -> StaticInfo:
        raise NotImplementedError

    def sample(self) -> GpuStats:
        raise NotImplementedError

    def processes(self, cpu_threshold: float = 20.0) -> List[ProcInfo]:
        raise NotImplementedError
