import os

from sonar.backends.apple import parse_displays, parse_gpu_power, parse_ioreg, parse_ps
from sonar.backends.nvidia import parse_compute_apps, parse_query_gpu, parse_sample

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def _read(name):
    with open(os.path.join(FIX, name)) as f:
        return f.read()


def test_parse_ioreg_real_fixture():
    d = parse_ioreg(_read("ioreg.txt"))
    assert "Device Utilization %" in d
    assert 0 <= d["Device Utilization %"] <= 100
    assert d["In use system memory"] > 0


def test_parse_ioreg_picks_block_with_device_util():
    text = (
        '"PerformanceStatistics" = {"Alloc system memory"=10}\n'
        '"PerformanceStatistics" = {"Device Utilization %"=77,"In use system memory"=5}'
    )
    d = parse_ioreg(text)
    assert d["Device Utilization %"] == 77


def test_parse_displays_real_fixture():
    name, cores = parse_displays(_read("displays.txt"))
    assert "Apple" in name
    assert cores and cores > 0


def test_parse_ps_filters_and_types():
    procs = parse_ps(_read("ps.txt"), cpu_threshold=20.0)
    assert procs, "expected at least one process from fixture"
    names = {p.name for p in procs}
    assert "sysmond" not in names
    assert "Activity" not in names
    assert "iTerm2" not in names
    assert "Terminal" not in names
    assert "WindowServer" not in names
    for p in procs:
        assert isinstance(p.pid, int)
        assert p.rss >= 0
        assert p.is_gpu


def test_parse_ps_excludes_pid():
    text = "111 99.0 1.0 1024 00:10 /usr/bin/python3\n222 99.0 1.0 1024 00:10 /usr/bin/python3"
    procs = parse_ps(text, exclude_pid=111)
    assert [p.pid for p in procs] == [222]


def test_parse_ps_shows_full_command_and_matches_on_exe():
    # args form: interpreter path + script + flags
    text = "555 80.0 4.0 200000 01:00:00 /Users/x/proj/.venv/bin/python3 train.py --config c.yaml"
    procs = parse_ps(text)
    assert len(procs) == 1
    p = procs[0]
    assert p.name == "python3"           # matched on executable
    assert p.is_gpu is True              # python => compute candidate
    assert p.cmd == "python3 train.py --config c.yaml"  # script visible


def test_parse_ps_excludes_assistant_shells_without_gpu_child():
    text = "\n".join(
        [
            "111 50.0 0.1 1000 00:01 /usr/libexec/sysmond",
            "222 30.0 0.4 2000 00:02 /Users/me/.local/share/claude/versions/2.1.177 --bg-spare",
            "333 20.0 0.4 2000 00:03 /Applications/Codex.app/Contents/MacOS/Codex",
            "444 25.0 0.4 2000 00:04 /Applications/Claude.app/Contents/MacOS/Claude",
            "555 15.0 4.0 200000 00:05 /Users/me/proj/.venv/bin/python train.py",
        ]
    )
    procs = parse_ps(text)
    assert [p.pid for p in procs] == [555]


def test_parse_ps_excludes_sonar_itself():
    text = "\n".join(
        [
            "111 20.0 0.1 1000 00:01 uv run sonar",
            "222 20.0 0.1 1000 00:02 /Users/me/code/sonar/.venv/bin/python3 /Users/me/code/sonar/.venv/bin/sonar",
            "333 20.0 0.1 1000 00:03 /Users/me/code/project/.venv/bin/python3 train.py",
        ]
    )
    procs = parse_ps(text)
    assert [p.pid for p in procs] == [333]


def test_parse_gpu_power():
    assert parse_gpu_power("GPU Power: 1234 mW\nother: x") == 1.234
    assert parse_gpu_power("no power here") is None


def test_nvidia_query_gpu_aggregates():
    text = "NVIDIA A100, 40960\nNVIDIA A100, 40960"
    info = parse_query_gpu(text)
    assert info.gpu_count == 2
    assert info.mem_total == 2 * 40960 * 1024 * 1024


def test_nvidia_sample_averages_util():
    text = "30, 1000, 40960, 55, 120.5\n70, 2000, 40960, 60, 130.0"
    s = parse_sample(text)
    assert abs(s.device_util - 50.0) < 1e-6
    assert s.mem_used == 3000 * 1024 * 1024
    assert s.temp_c == 60
    assert abs(s.power_w - 250.5) < 1e-6


def test_nvidia_compute_apps():
    m = parse_compute_apps("1234, 512\n5678, 1024")
    assert m[1234] == 512 * 1024 * 1024
    assert m[5678] == 1024 * 1024 * 1024
