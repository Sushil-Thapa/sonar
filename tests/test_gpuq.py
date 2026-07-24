import json
from pathlib import Path

from sonar.gpuq import read_gpuq


def write_json(path: Path, obj: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj) + "\n", encoding="utf-8")


def test_read_gpuq_running_and_queued_with_step_eta(tmp_path):
    home = tmp_path / ".gpuq"
    (home / "logs").mkdir(parents=True)
    (home / "jobs").mkdir()
    workdir = tmp_path / "proj"
    (workdir / "scripts").mkdir(parents=True)
    (workdir / "scripts" / "run_train.sh").write_text(
        "python train.py \\\n  --max-steps 200 \\\n  --output out\n",
        encoding="utf-8",
    )
    running_id = "demo-train-20260620T010000"
    queued_id = "demo-next-20260620T011000"
    write_json(
        home / "state.json",
        {
            "gpu": "busy",
            "paused": False,
            "lease": {
                "job_id": running_id,
                "pid": 123,
                "started": "2026-06-20T01:00:00+00:00",
            },
        },
    )
    write_json(
        home / "jobs" / f"{running_id}.json",
        {
            "id": running_id,
            "project": "demo",
            "name": "train",
            "workdir": str(workdir),
            "cmd": "bash scripts/run_train.sh",
            "priority": 90,
            "status": "running",
            "submitted": "2026-06-20T00:59:00+00:00",
            "history": [{"event": "JOB_START", "ts": "2026-06-20T01:00:00+00:00", "pid": 123}],
        },
    )
    (home / "logs" / f"{running_id}.log").write_text("step=10 loss=2\nstep=50 loss=1\n", encoding="utf-8")
    queued = {
        "id": queued_id,
        "project": "demo",
        "name": "next",
        "workdir": str(workdir),
        "cmd": "bash scripts/run_train.sh",
        "priority": 80,
        "status": "queued",
        "submitted": "2026-06-20T01:10:00+00:00",
        "history": [],
    }
    (home / "queue.jsonl").write_text(json.dumps(queued) + "\n", encoding="utf-8")

    snap = read_gpuq(str(home))

    assert snap.available is True
    assert snap.running is not None
    assert snap.running.id == running_id
    assert snap.running.progress_current == 50
    assert snap.running.progress_total == 200
    assert snap.running.eta_seconds is not None
    assert len(snap.queued) == 1
    assert snap.queued[0].id == queued_id


def test_read_gpuq_unavailable(tmp_path):
    snap = read_gpuq(str(tmp_path / "missing"))
    assert snap.available is False
