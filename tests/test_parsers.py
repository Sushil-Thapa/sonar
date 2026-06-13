import os

from sonar.backends.apple import parse_displays, parse_ioreg, parse_ps
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
    for p in procs:
        assert isinstance(p.pid, int)
        assert p.rss >= 0
        # kept either as a compute candidate or for high CPU
        assert p.is_gpu or p.cpu >= 20.0


def test_parse_ps_excludes_pid():
    text = "111 99.0 1.0 1024 00:10 /usr/bin/python3\n222 99.0 1.0 1024 00:10 /usr/bin/python3"
    procs = parse_ps(text, exclude_pid=111)
    assert [p.pid for p in procs] == [222]


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
