from sonar.hints import evaluate
from sonar.model import GpuStats, ProcInfo, StaticInfo

STATIC = StaticInfo(backend="apple", gpu_name="Apple M4 Pro", cores=16, mem_total=48 * 1024**3)


def _proc(pid=1, project="alpha", is_gpu=True):
    return ProcInfo(pid=pid, name="python3", cmd="python3", cpu=80, project=project, is_gpu=is_gpu)


def test_healthy_when_nothing_notable():
    hs = evaluate(STATIC, GpuStats(device_util=70, mem_used=10 * 1024**3, mem_total=48 * 1024**3),
                  [_proc()], [70, 70, 70, 70, 70])
    assert any(h.severity == "info" and "healthy" in h.text for h in hs)


def test_memory_pressure_crit():
    hs = evaluate(STATIC, GpuStats(device_util=80, mem_used=46 * 1024**3, mem_total=48 * 1024**3),
                  [_proc()], [80] * 8)
    assert any(h.severity == "crit" for h in hs)


def test_coresident_warns():
    hs = evaluate(STATIC, GpuStats(device_util=80, mem_used=1, mem_total=48 * 1024**3),
                  [_proc(1, "alpha"), _proc(2, "beta")], [80] * 8)
    assert any(h.severity == "warn" and "co-resident" in h.text for h in hs)


def test_stall_detected():
    hs = evaluate(STATIC, GpuStats(device_util=1, mem_used=1, mem_total=48 * 1024**3),
                  [_proc()], [1, 0, 2, 1, 0, 1])
    assert any("stall" in h.text or "bottleneck" in h.text for h in hs)


def test_underutilized():
    hs = evaluate(STATIC, GpuStats(device_util=20, mem_used=1, mem_total=48 * 1024**3),
                  [_proc()], [20, 18, 22, 19, 21])
    assert any("underutilized" in h.text for h in hs)


def test_unattributed_load():
    hs = evaluate(STATIC, GpuStats(device_util=90, mem_used=1, mem_total=48 * 1024**3),
                  [], [90] * 8)
    assert any("no compute process" in h.text for h in hs)
