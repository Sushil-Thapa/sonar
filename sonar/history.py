"""Rolling in-memory history plus JSONL persistence.

The ring buffers feed the live timeline. A rolling persistence file lets the
dashboard survive terminal/app restarts, while the optional log file answers the
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


def default_history_path() -> str:
    return os.path.join(os.path.expanduser("~/.sonar"), "history-24h.jsonl")


class History:
    def __init__(
        self,
        maxlen: int = 120,
        logpath: Optional[str] = None,
        persist_path: Optional[str] = None,
        retention_seconds: Optional[float] = None,
    ):
        self.ts = deque(maxlen=maxlen)
        self.util = deque(maxlen=maxlen)
        self.mem = deque(maxlen=maxlen)
        self.owner = deque(maxlen=maxlen)  # owning project per tick (None = idle/unattributed)
        self.logpath = logpath
        self.persist_path = persist_path
        self.retention_seconds = retention_seconds
        self._log_fh = None
        self._persist_fh = None
        if persist_path:
            self._load_persisted()
            os.makedirs(os.path.dirname(persist_path), exist_ok=True)
            self._persist_fh = open(persist_path, "a", encoding="utf-8")
        if logpath:
            os.makedirs(os.path.dirname(logpath), exist_ok=True)
            self._log_fh = open(logpath, "a", encoding="utf-8")

    def _cutoff(self) -> Optional[float]:
        if not self.retention_seconds:
            return None
        return time.time() - self.retention_seconds

    def _load_persisted(self) -> None:
        if not self.persist_path or not os.path.exists(self.persist_path):
            return
        cutoff = self._cutoff()
        try:
            with open(self.persist_path, encoding="utf-8") as handle:
                for line in handle:
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ts = rec.get("ts")
                    if ts is None or (cutoff is not None and ts < cutoff):
                        continue
                    self.ts.append(float(ts))
                    self.util.append(float(rec.get("util") or 0.0))
                    self.mem.append(rec.get("mem_used") or 0)
                    self.owner.append(rec.get("top_project"))
        except OSError:
            return

    def _records(self):
        cutoff = self._cutoff()
        for ts, util, mem, owner in zip(self.ts, self.util, self.mem, self.owner):
            if cutoff is not None and ts < cutoff:
                continue
            yield {
                "ts": round(float(ts), 1),
                "util": round(float(util), 1),
                "mem_used": mem,
                "top_project": owner,
                "top_pid": None,
            }

    def add(self, stats: GpuStats, procs: List[ProcInfo]) -> None:
        top = max(procs, key=lambda p: (p.gpu_mem or 0, p.cpu), default=None)
        ts = time.time()
        self.ts.append(ts)
        self.util.append(stats.device_util)
        self.mem.append(stats.mem_used or 0)
        self.owner.append(top.project if top else None)
        rec = {
            "ts": round(ts, 1),
            "util": round(stats.device_util, 1),
            "mem_used": stats.mem_used,
            "top_project": top.project if top else None,
            "top_pid": top.pid if top else None,
        }
        for fh in (self._persist_fh, self._log_fh):
            if fh:
                fh.write(json.dumps(rec) + "\n")
                fh.flush()

    def close(self) -> None:
        if self._persist_fh:
            self._persist_fh.close()
            self._persist_fh = None
            self._rewrite_persisted()
        if self._log_fh:
            self._log_fh.close()
            self._log_fh = None

    def _rewrite_persisted(self) -> None:
        if not self.persist_path:
            return
        try:
            os.makedirs(os.path.dirname(self.persist_path), exist_ok=True)
            tmp = f"{self.persist_path}.tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                for rec in self._records():
                    handle.write(json.dumps(rec) + "\n")
            os.replace(tmp, self.persist_path)
        except OSError:
            return
