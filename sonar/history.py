"""Rolling in-memory history (for the sparkline) plus optional JSONL logging.

The ring buffers feed the live sparkline; the optional log file answers the
"which project owned the GPU across the day" question after the fact.
"""

from __future__ import annotations

import datetime
import json
import os
import time
from collections import deque
from typing import List, Optional

from .model import GpuStats, ProcInfo


def default_logpath() -> str:
    return os.path.join(
        os.path.expanduser("~/.sonar"),
        f"log-{datetime.date.today().isoformat()}.jsonl",
    )


class History:
    def __init__(self, maxlen: int = 120, logpath: Optional[str] = None):
        self.util = deque(maxlen=maxlen)
        self.mem = deque(maxlen=maxlen)
        self.logpath = logpath
        self._fh = None
        if logpath:
            os.makedirs(os.path.dirname(logpath), exist_ok=True)
            self._fh = open(logpath, "a")

    def add(self, stats: GpuStats, procs: List[ProcInfo]) -> None:
        self.util.append(stats.device_util)
        self.mem.append(stats.mem_used or 0)
        if self._fh:
            top = max(procs, key=lambda p: (p.gpu_mem or 0, p.cpu), default=None)
            rec = {
                "ts": round(time.time(), 1),
                "util": round(stats.device_util, 1),
                "mem_used": stats.mem_used,
                "top_project": top.project if top else None,
                "top_pid": top.pid if top else None,
            }
            self._fh.write(json.dumps(rec) + "\n")
            self._fh.flush()

    def close(self) -> None:
        if self._fh:
            self._fh.close()
            self._fh = None
