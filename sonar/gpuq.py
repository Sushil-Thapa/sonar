"""Cheap reader for scheduler/gpuq state.

sonar should not drive the scheduler. It only reads gpuq's local state files so
the live TUI can show which experiment is running and what is queued.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .model import GpuqJob, GpuqSnapshot


_TS_RE = re.compile(r"-\d{8}T\d{6}$")
_STEP_RE = re.compile(r"\bstep=(\d+)\b")
_GENERATED_RE = re.compile(r"([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+): generated (\d+)/(\d+)")
_MAX_STEPS_RE = re.compile(r"--max-steps\s+(?:\"|\')?(\d+)")


def default_gpuq_home() -> str:
    return os.environ.get("GPUQ_HOME") or os.path.join(os.path.expanduser("~"), ".gpuq")


def _parse_ts(value: Any) -> Optional[float]:
    if not value:
        return None
    try:
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).replace("Z", "+00:00")
        return datetime.fromisoformat(text).timestamp()
    except (TypeError, ValueError):
        return None


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _read_queue(path: Path) -> list[dict]:
    rows: list[dict] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return rows
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _tail(path: Path, limit: int = 65536) -> str:
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - limit))
            return handle.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def _short_id(job_id: str) -> str:
    parts = job_id.split("-", 1)
    return parts[1] if len(parts) == 2 else job_id


def _name_without_stamp(name: str) -> str:
    return _TS_RE.sub("", name)


def _script_from_cmd(workdir: str, cmd: str) -> Optional[Path]:
    # Covers the current gpuq pattern: bash scripts/run_foo.sh
    match = re.search(r"\bbash\s+([^\s;&|]+\.sh)\b", cmd)
    if not match:
        return None
    path = Path(match.group(1))
    if not path.is_absolute():
        path = Path(workdir) / path
    return path


def _max_steps(workdir: str, cmd: str) -> Optional[int]:
    script = _script_from_cmd(workdir, cmd)
    if script:
        text = _tail(script, limit=32768)
        match = _MAX_STEPS_RE.search(text)
        if match:
            return int(match.group(1))
    match = _MAX_STEPS_RE.search(cmd)
    return int(match.group(1)) if match else None


def _progress_from_log(log_text: str) -> tuple[Optional[int], Optional[int], str]:
    generated = list(_GENERATED_RE.finditer(log_text))
    if generated:
        last = generated[-1]
        return int(last.group(2)), int(last.group(3)), last.group(1)
    steps = [int(m.group(1)) for m in _STEP_RE.finditer(log_text)]
    if steps:
        return max(steps), None, "train"
    return None, None, ""


def _job_from_dict(
    data: dict,
    *,
    home: Path,
    state_started: Optional[float] = None,
    pid: Optional[int] = None,
    now: Optional[float] = None,
) -> GpuqJob:
    now = time.time() if now is None else now
    started = state_started
    for event in data.get("history", []):
        if event.get("event") == "JOB_START":
            started = _parse_ts(event.get("ts")) or started
            pid = event.get("pid") or pid

    submitted = _parse_ts(data.get("submitted"))
    elapsed = max(0.0, now - started) if started else None
    wait = max(0.0, now - submitted) if submitted and not started else None

    job = GpuqJob(
        id=str(data.get("id") or ""),
        project=str(data.get("project") or ""),
        name=str(data.get("name") or _name_without_stamp(_short_id(str(data.get("id") or "")))),
        status=str(data.get("status") or ""),
        cmd=str(data.get("cmd") or ""),
        priority=data.get("priority"),
        workdir=str(data.get("workdir") or ""),
        pid=pid,
        submitted=submitted,
        started=started,
        elapsed_seconds=elapsed,
        wait_seconds=wait,
    )

    log_text = _tail(home / "logs" / f"{job.id}.log")
    cur, total, label = _progress_from_log(log_text)
    if total is None:
        total = _max_steps(job.workdir, job.cmd)
    job.progress_current = cur
    job.progress_total = total
    job.progress_label = label

    if elapsed and cur and total and cur > 0 and total >= cur:
        total_est = elapsed * total / cur
        job.eta_seconds = max(0.0, total_est - elapsed)
    return job


def read_gpuq(home: Optional[str] = None) -> GpuqSnapshot:
    root = Path(home or default_gpuq_home()).expanduser()
    if not root.exists():
        return GpuqSnapshot(available=False)
    now = time.time()
    try:
        state = _read_json(root / "state.json")
        queue_rows = _read_queue(root / "queue.jsonl")
        lease = state.get("lease") or {}
        running = None
        if lease.get("job_id"):
            job_path = root / "jobs" / f"{lease['job_id']}.json"
            data = _read_json(job_path)
            if data:
                running = _job_from_dict(
                    data,
                    home=root,
                    state_started=_parse_ts(lease.get("started")),
                    pid=lease.get("pid"),
                    now=now,
                )
                running.status = "running"
        queued = [_job_from_dict(row, home=root, now=now) for row in queue_rows]
        for job in queued:
            job.status = "queued"
        if running and running.elapsed_seconds and running.progress_current:
            seconds_per_unit = running.elapsed_seconds / max(1, running.progress_current)
            for job in queued:
                if job.eta_seconds is None and job.progress_total:
                    job.eta_seconds = seconds_per_unit * job.progress_total
        return GpuqSnapshot(
            available=True,
            paused=bool(state.get("paused")),
            running=running,
            queued=queued,
            updated_at=now,
        )
    except Exception as exc:
        return GpuqSnapshot(available=True, error=str(exc), updated_at=now)
