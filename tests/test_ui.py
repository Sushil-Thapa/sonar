from rich.console import Console

from sonar.history import History
from sonar.model import GpuqJob, GpuqSnapshot
from sonar.ui import _gpuq_panel, _history_panel, owner_colors, ownership_strip, timeline_axis, usage_bar_chart


def test_owner_colors_stable_and_distinct():
    c = owner_colors(["B", "A", "A", None, "C"])
    assert set(c) == {"A", "B", "C"}
    assert len({c["A"], c["B"], c["C"]}) == 3  # distinct within palette size
    # sorted assignment => deterministic across calls
    assert owner_colors(["A", "B", "C"]) == c


def test_ownership_strip_marks_idle_grey():
    colors = owner_colors(["alpha"])
    strip = ownership_strip([90, 1, 90], ["alpha", "alpha", None], colors, width=3)
    styles = [str(sp.style) for sp in strip.spans]
    # middle block is idle (util<5) -> grey; others colored
    assert "grey30" in styles[1]
    assert "grey30" not in styles[0]


def test_history_panel_shows_window_and_util_stats():
    hist = History(maxlen=57600)
    hist.util.extend([0, 50, 100])
    console = Console(record=True, width=140, color_system=None)
    console.print(_history_panel(hist, interval=1.5, width=12))
    out = console.export_text()
    assert "GPU usage timeline" in out
    assert "100% │" in out
    assert " 50% │" in out
    assert " 10% │" in out
    assert "  0% └" in out
    assert "-4s ago" in out
    assert "now" in out
    assert "showing last 4s of 1d" in out
    assert "avg 50%" in out
    assert "min/max/latest 0/100/100%" in out
    assert "active 67%" in out


def test_timeline_axis_labels_visible_range():
    axis = timeline_axis([0] * 96, interval=900, width=96)
    assert "-1d ago" in axis.plain
    assert axis.plain.endswith("now")


def test_usage_bar_chart_fills_by_percent_level():
    rows = usage_bar_chart([0, 25, 50, 75, 100], width=5)
    text = [r.plain for r in rows]
    assert text[0].endswith("    █")      # 100%
    assert text[1].endswith("    █")      # 90%+
    assert text[2].endswith("   ██")      # 80% band includes 75% and 100%
    assert text[5].endswith("  ███")      # 50%+
    assert text[9].endswith(" ████")      # 10% band includes all non-zero
    assert text[10].endswith("─────")     # 0% axis


def test_gpuq_panel_shows_running_and_queued_jobs():
    snap = GpuqSnapshot(
        available=True,
        running=GpuqJob(
            id="demo-run-1",
            project="demo",
            name="run-1",
            status="running",
            elapsed_seconds=120,
            eta_seconds=240,
            progress_current=10,
            progress_total=40,
            progress_label="train",
        ),
        queued=[
            GpuqJob(
                id="demo-next-1",
                project="demo",
                name="next-1",
                status="queued",
                priority=89,
                wait_seconds=30,
            )
        ],
    )
    console = Console(record=True, width=120, color_system=None)
    console.print(_gpuq_panel(snap))
    out = console.export_text()
    assert "gpuq queue" in out
    assert "run-1" in out
    assert "train 10/40 25%" in out
    assert "done ~" in out
    assert "4m" in out
    assert "next-1" in out
    assert "starts ~" in out

def test_gpuq_panel_collapses_overflow_when_capped():
    queued = [
        GpuqJob(id=f"demo-q{i}", project="demo", name=f"job-{i}",
                status="queued", priority=15)
        for i in range(12)
    ]
    snap = GpuqSnapshot(available=True, running=None, queued=queued)
    console = Console(record=True, width=120, color_system=None)
    console.print(_gpuq_panel(snap, max_lines=5))
    out = console.export_text()
    # 5 interior lines = 4 job rows + one "+N more" summary line
    assert "job-0" in out and "job-3" in out
    assert "job-4" not in out
    assert "+8 more queued" in out
    assert "prio 15" in out


def test_gpuq_panel_shows_all_queued_when_uncapped():
    queued = [
        GpuqJob(id=f"demo-q{i}", project="demo", name=f"job-{i}", status="queued")
        for i in range(12)
    ]
    snap = GpuqSnapshot(available=True, running=None, queued=queued)
    console = Console(record=True, width=120, color_system=None)
    console.print(_gpuq_panel(snap))
    out = console.export_text()
    assert "job-11" in out
    assert "more queued" not in out
