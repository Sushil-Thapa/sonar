import json

from sonar.history import History, default_history_path
from sonar.model import GpuStats, ProcInfo


def test_default_history_path_is_rolling_cache():
    assert default_history_path().endswith("history-24h.jsonl")


def test_history_loads_recent_persisted_samples(tmp_path, monkeypatch):
    path = tmp_path / "history-24h.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps({"ts": 10.0, "util": 90, "mem_used": 1, "top_project": "old"}),
                json.dumps({"ts": 95.0, "util": 50, "mem_used": 2, "top_project": "fresh"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sonar.history.time.time", lambda: 100.0)

    hist = History(maxlen=10, persist_path=str(path), retention_seconds=20)
    try:
        assert list(hist.util) == [50.0]
        assert list(hist.owner) == ["fresh"]
        assert list(hist.ts) == [95.0]
    finally:
        hist.close()


def test_history_persists_and_prunes_on_close(tmp_path, monkeypatch):
    path = tmp_path / "history-24h.jsonl"
    times = iter([100.0, 100.0, 130.0, 130.0])
    monkeypatch.setattr("sonar.history.time.time", lambda: next(times))

    hist = History(maxlen=10, persist_path=str(path), retention_seconds=60)
    hist.add(GpuStats(device_util=12.3, mem_used=4), [])
    hist.add(
        GpuStats(device_util=98.7, mem_used=8),
        [ProcInfo(pid=42, name="python", cmd="python train.py", cpu=250, project="train")],
    )
    hist.close()

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [row["util"] for row in rows] == [12.3, 98.7]
    assert rows[-1]["top_project"] == "train"
