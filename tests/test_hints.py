from sonar.hints import evaluate
from sonar.model import GpuStats, ProcInfo, StaticInfo

STATIC = StaticInfo(backend="apple", gpu_name="Apple M4 Pro", cores=16, mem_total=48 * 1024**3)


def _proc(pid=1, project="alpha", is_gpu=True, cpu=80):
    return ProcInfo(pid=pid, name="python3", cmd="python3", cpu=cpu, project=project, is_gpu=is_gpu)


def test_healthy_when_nothing_notable():
    hs = evaluate(STATIC, GpuStats(device_util=70, mem_used=10 * 1024**3, mem_total=48 * 1024**3),
                  [_proc()], [70, 70, 70, 70, 70])
    assert any(h.severity == "info" and "healthy" in h.text for h in hs)


def test_memory_pressure_crit():
    hs = evaluate(STATIC, GpuStats(device_util=80, mem_used=46 * 1024**3, mem_total=48 * 1024**3),
                  [_proc()], [80] * 8)
    assert any(h.severity == "crit" for h in hs)


def test_coresident_warns_for_active_runs():
    hs = evaluate(STATIC, GpuStats(device_util=80, mem_used=1, mem_total=48 * 1024**3),
                  [_proc(1, "alpha", cpu=80), _proc(2, "beta", cpu=70)], [80] * 8)
    assert any(h.severity == "warn" and "co-resident" in h.text for h in hs)


def test_idle_kernel_does_not_trip_coresident():
    # One real run + a parked kernel (low CPU, no GPU mem) -> no co-resident warn.
    hs = evaluate(STATIC, GpuStats(device_util=80, mem_used=1, mem_total=48 * 1024**3),
                  [_proc(1, "alpha", cpu=85), _proc(2, "notebook", cpu=2)], [80] * 8)
    assert not any("co-resident" in h.text for h in hs)


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
    assert any("no GPU-run process" in h.text for h in hs)
