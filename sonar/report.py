"""Retrospective rollup of a JSONL log into per-project GPU time.

Answers "where did the scarce GPU go today, and how much did it sit idle?"
summarize() is a pure function over already-parsed records so it's easy to test.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from typing import List, Optional

_IDLE = 5.0  # util below this counts as idle, not attributable to a project


@dataclass
class ProjectStat:
    project: str
    seconds: float


@dataclass
class Summary:
    span_seconds: float = 0.0
    active_seconds: float = 0.0
    idle_seconds: float = 0.0
    avg_util: float = 0.0
    samples: int = 0
    projects: List[ProjectStat] = field(default_factory=list)


def load_records(path: str) -> List[dict]:
    recs: List[dict] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                recs.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return recs


def summarize(records: List[dict], idle_util: float = _IDLE) -> Summary:
    """Attribute elapsed time between samples to the owning project.

    Each sample contributes the (clamped) gap until the next sample to its
    owner's bucket, or to idle if the GPU was idle/unattributed. Clamping
    prevents a long pause (laptop asleep, sonar not running) from being charged
    as continuous GPU time.
    """
    recs = sorted((r for r in records if "ts" in r), key=lambda r: r["ts"])
    n = len(recs)
    if n == 0:
        return Summary()

    ts = [r["ts"] for r in recs]
    deltas = [ts[i + 1] - ts[i] for i in range(n - 1)]
    interval = statistics.median(deltas) if deltas else 1.5
    cap = max(interval * 5, interval)

    per: dict = {}
    active = idle = 0.0
    utils: List[float] = []
    for i, r in enumerate(recs):
        dt = min(max(ts[i + 1] - ts[i], 0.0), cap) if i < n - 1 else interval
        u = float(r.get("util") or 0)
        utils.append(u)
        proj = r.get("top_project")
        if u >= idle_util and proj:
            per[proj] = per.get(proj, 0.0) + dt
            active += dt
        else:
            idle += dt

    projects = sorted(
        (ProjectStat(p, s) for p, s in per.items()),
        key=lambda x: x.seconds,
        reverse=True,
    )
    return Summary(
        span_seconds=ts[-1] - ts[0],
        active_seconds=active,
        idle_seconds=idle,
        avg_util=sum(utils) / len(utils) if utils else 0.0,
        samples=n,
        projects=projects,
    )
