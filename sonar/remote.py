"""Reader for remote host snapshots dropped into <gpuq-home>/remote/*.json.

Some setups run jobs on remote clusters as well as the local machine. An
out-of-band probe (not part of sonar) writes one small JSON file per remote
host into <gpuq-home>/remote/, and sonar only reads them so the live TUI can
show remote GPUs beside the local queue.

Every key is optional and files may be written by an older probe, so parsing is
fully defensive: an unreadable, empty, or partial file degrades to as much as
can be salvaged (or is skipped) and never raises.

Expected shape (all keys optional)::

    {
      "ts": <epoch seconds>,
      "host": "<name>",
      "du": "<disk usage>",              # or a "du_*" variant key
      "jobs": [{"id", "state", "name", "elapsed", "gres", "node"}],
      "host_status": {
        "ts": <epoch seconds>,
        "allocs": [{"user", "node", "gres", "state", "jobname", "elapsed"}],
        "nodes": {
          "<node>": {
            "reachable": <bool>,
            "gpus": [{"i", "util_pct", "mem_used_mib", "mem_total_mib", "users": [<str>]}]
          }
        }
      }
    }
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, List, Optional

from .model import RemoteAlloc, RemoteGpu, RemoteHost, RemoteNode

# A snapshot older than this is almost certainly a probe that stopped running,
# so the reader flags it rather than presenting stale numbers as live.
STALE_SECONDS = 30 * 60


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def _num(value: Any) -> Optional[float]:
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> Optional[int]:
    n = _num(value)
    return int(n) if n is not None else None


def _str(value: Any) -> str:
    return "" if value is None else str(value)


def _disk_usage(data: dict) -> Optional[str]:
    """Disk usage under a generic "du" key or any project-specific "du_*" key."""
    if data.get("du") is not None:
        return _str(data.get("du"))
    for key, value in data.items():
        if isinstance(key, str) and key.startswith("du_") and value is not None:
            return _str(value)
    return None


def _gpu_from_dict(data: dict) -> RemoteGpu:
    users = data.get("users")
    users = [_str(u) for u in users] if isinstance(users, list) else []
    return RemoteGpu(
        index=_int(data.get("i")) or 0,
        util_pct=_num(data.get("util_pct")) or 0.0,
        mem_used_mib=_int(data.get("mem_used_mib")),
        mem_total_mib=_int(data.get("mem_total_mib")),
        users=users,
    )


def _node_from_dict(name: str, data: dict) -> RemoteNode:
    gpus_raw = data.get("gpus")
    gpus = [_gpu_from_dict(g) for g in gpus_raw if isinstance(g, dict)] if isinstance(gpus_raw, list) else []
    return RemoteNode(name=name, reachable=bool(data.get("reachable")), gpus=gpus)


def _alloc_from_dict(data: dict) -> RemoteAlloc:
    return RemoteAlloc(
        user=_str(data.get("user")),
        node=_str(data.get("node")),
        gres=_str(data.get("gres")),
        state=_str(data.get("state")),
        jobname=_str(data.get("jobname")),
        elapsed=_str(data.get("elapsed")),
    )


def _host_from_dict(data: dict, fallback_name: str, now: float) -> RemoteHost:
    ts = _num(data.get("ts"))
    age = max(0.0, now - ts) if ts is not None else None

    jobs = data.get("jobs")
    n_jobs = len(jobs) if isinstance(jobs, list) else 0

    status = data.get("host_status")
    status = status if isinstance(status, dict) else {}

    nodes_raw = status.get("nodes")
    nodes: List[RemoteNode] = []
    if isinstance(nodes_raw, dict):
        for node_name in sorted(nodes_raw):
            node_data = nodes_raw.get(node_name)
            if isinstance(node_data, dict):
                nodes.append(_node_from_dict(_str(node_name), node_data))

    allocs_raw = status.get("allocs")
    allocs = [_alloc_from_dict(a) for a in allocs_raw if isinstance(a, dict)] if isinstance(allocs_raw, list) else []

    return RemoteHost(
        host=_str(data.get("host")) or fallback_name,
        ts=ts,
        age_seconds=age,
        stale=age is not None and age > STALE_SECONDS,
        disk_usage=_disk_usage(data),
        n_jobs=n_jobs,
        nodes=nodes,
        allocs=allocs,
    )


def remote_dir(gpuq_home: str) -> Path:
    return Path(gpuq_home).expanduser() / "remote"


def read_remote_hosts(gpuq_home: str, now: Optional[float] = None) -> List[RemoteHost]:
    """Load every remote host snapshot under <gpuq-home>/remote/*.json.

    Returns an empty list when no such directory or files exist, so the feature
    is zero-cost (and renders nothing) for anyone not driving remote clusters.
    """
    root = remote_dir(gpuq_home)
    if not root.is_dir():
        return []
    now = time.time() if now is None else now
    hosts: List[RemoteHost] = []
    for path in sorted(root.glob("*.json")):
        data = _read_json(path)
        if not isinstance(data, dict) or not data:
            continue
        try:
            hosts.append(_host_from_dict(data, path.stem, now))
        except Exception:
            # A single malformed file must never take down the reader.
            continue
    return hosts
