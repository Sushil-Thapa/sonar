import json
from pathlib import Path

from rich.console import Console, Group

from sonar.model import GpuqSnapshot
from sonar.remote import STALE_SECONDS, read_remote_hosts
from sonar.ui import _gpuq_panel, _remote_lines

NOW = 1_700_000_000.0


def write_remote(home: Path, name: str, obj) -> None:
    d = home / "remote"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.json").write_text(json.dumps(obj) + "\n", encoding="utf-8")


def new_schema_host():
    return {
        "ts": NOW - 120,
        "host": "cluster1",
        "du": "9.5G",
        "jobs": [
            {"id": "1", "state": "RUNNING", "name": "train-run", "elapsed": "2:00", "gres": "gres:gpu:1", "node": "node-a"},
            {"id": "2", "state": "PENDING", "name": "train-run", "elapsed": "0:00", "gres": "gres:gpu:1", "node": ""},
        ],
        "host_status": {
            "ts": NOW - 120,
            "allocs": [
                {"user": "alice", "node": "node-a", "gres": "gres:gpu:1", "state": "RUNNING", "jobname": "train-run", "elapsed": "2:00"},
                {"user": "bob", "node": "", "gres": "gres:gpu:1", "state": "PENDING", "jobname": "eval-run", "elapsed": "0:00"},
            ],
            "nodes": {
                "node-a": {
                    "reachable": True,
                    "gpus": [
                        {"i": 0, "util_pct": 90, "mem_used_mib": 12000, "mem_total_mib": 24000, "users": ["alice"]},
                        {"i": 1, "util_pct": 0, "mem_used_mib": 0, "mem_total_mib": 24000, "users": []},
                    ],
                },
                "node-b": {"reachable": False, "gpus": []},
            },
        },
    }


def test_new_schema_parses_fully(tmp_path):
    write_remote(tmp_path, "cluster1", new_schema_host())
    hosts = read_remote_hosts(str(tmp_path), now=NOW)
    assert len(hosts) == 1
    h = hosts[0]
    assert h.host == "cluster1"
    assert h.n_jobs == 2
    assert h.disk_usage == "9.5G"
    assert h.age_seconds == 120
    assert h.stale is False
    assert [n.name for n in h.nodes] == ["node-a", "node-b"]
    node_a = h.nodes[0]
    assert node_a.reachable is True
    assert len(node_a.gpus) == 2
    assert node_a.gpus[0].util_pct == 90
    assert node_a.gpus[0].users == ["alice"]
    assert h.nodes[1].reachable is False
    assert len(h.allocs) == 2


def test_old_schema_without_host_status(tmp_path):
    write_remote(tmp_path, "cluster2", {
        "ts": NOW - 60,
        "host": "cluster2",
        "du_scratch": "3.1T",  # project-specific du_* variant key
        "jobs": [{"id": "9", "state": "RUNNING", "name": "train-run"}],
    })
    hosts = read_remote_hosts(str(tmp_path), now=NOW)
    assert len(hosts) == 1
    h = hosts[0]
    assert h.host == "cluster2"
    assert h.n_jobs == 1
    assert h.disk_usage == "3.1T"  # picked up the du_* variant
    assert h.nodes == []
    assert h.allocs == []
    assert h.stale is False


def test_tolerates_corrupt_and_non_object_files(tmp_path):
    write_remote(tmp_path, "cluster1", new_schema_host())
    d = tmp_path / "remote"
    (d / "broken.json").write_text("{not valid json,,,", encoding="utf-8")
    (d / "list.json").write_text("[1, 2, 3]", encoding="utf-8")  # valid JSON, wrong type
    (d / "empty.json").write_text("", encoding="utf-8")
    hosts = read_remote_hosts(str(tmp_path), now=NOW)
    # only the one good file survives; nothing raised
    assert [h.host for h in hosts] == ["cluster1"]


def test_missing_ts_is_not_stale_and_uses_filename(tmp_path):
    write_remote(tmp_path, "cluster3", {"jobs": [], "host_status": {}})
    hosts = read_remote_hosts(str(tmp_path), now=NOW)
    assert len(hosts) == 1
    assert hosts[0].host == "cluster3"  # fell back to the file stem
    assert hosts[0].age_seconds is None
    assert hosts[0].stale is False


def test_old_snapshot_marked_stale(tmp_path):
    obj = new_schema_host()
    obj["ts"] = NOW - (STALE_SECONDS + 600)
    write_remote(tmp_path, "cluster1", obj)
    hosts = read_remote_hosts(str(tmp_path), now=NOW)
    assert hosts[0].stale is True


def test_no_remote_dir_returns_empty(tmp_path):
    assert read_remote_hosts(str(tmp_path), now=NOW) == []


def _render(lines):
    console = Console(record=True, width=120, color_system=None)
    console.print(Group(*lines))
    return console.export_text()


def test_remote_lines_render_smoke(tmp_path):
    write_remote(tmp_path, "cluster1", new_schema_host())
    hosts = read_remote_hosts(str(tmp_path), now=NOW)
    out = _render(_remote_lines(hosts))
    assert "remote hosts" in out
    assert "cluster1" in out
    assert "age 2m" in out
    assert "jobs=2" in out
    assert "du 9.5G" in out
    assert "node-a gpu0" in out
    assert "90%" in out
    assert "12.0/24.0G" in out
    assert "alice(train-run)" in out
    assert "node-b (no probe)" in out


def test_remote_lines_render_stale_and_unreachable_alloc(tmp_path):
    obj = new_schema_host()
    obj["ts"] = NOW - (STALE_SECONDS + 600)
    # Move alice's allocation onto the unreachable node so it renders as alloc text.
    obj["host_status"]["allocs"][0]["node"] = "node-b"
    write_remote(tmp_path, "cluster1", obj)
    hosts = read_remote_hosts(str(tmp_path), now=NOW)
    out = _render(_remote_lines(hosts))
    assert "STALE" in out
    assert "node-b (no probe) alloc: alice gres:gpu:1 RUNNING train-run" in out


def test_remote_lines_empty_when_no_hosts():
    assert _remote_lines([]) == []


def test_gpuq_panel_includes_remote_block(tmp_path):
    write_remote(tmp_path, "cluster1", new_schema_host())
    hosts = read_remote_hosts(str(tmp_path), now=NOW)
    snap = GpuqSnapshot(available=True, running=None, queued=[], remote_hosts=hosts)
    console = Console(record=True, width=120, color_system=None)
    console.print(_gpuq_panel(snap, max_lines=20))
    out = console.export_text()
    assert "gpuq queue" in out
    assert "remote hosts" in out
    assert "cluster1" in out
    assert "node-a gpu0" in out


def test_gpuq_panel_no_remote_when_absent():
    snap = GpuqSnapshot(available=True, running=None, queued=[])
    console = Console(record=True, width=120, color_system=None)
    console.print(_gpuq_panel(snap, max_lines=20))
    out = console.export_text()
    assert "remote hosts" not in out
