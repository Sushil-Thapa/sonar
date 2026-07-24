"""Rich rendering: builds a full-screen Layout from the latest data.

render() is a pure function of (static, stats, procs, hints, history) so the
same code path serves both the live loop and the --once snapshot.
"""

from __future__ import annotations

import time
from collections import Counter
from typing import List

from rich.align import Align
from rich.box import ROUNDED
from rich.console import Group
from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .model import GpuqJob, GpuqSnapshot, GpuStats, Hint, ProcInfo, StaticInfo
from .util import human_bytes, human_duration

_SPARK = "▁▂▃▄▅▆▇█"
# Stable-ish palette for per-project ownership coloring (idle is grey).
_PALETTE = [
    "cyan", "magenta", "green", "yellow", "blue", "bright_red",
    "bright_cyan", "bright_magenta", "bright_green", "bright_yellow",
]
_IDLE_UTIL = 5.0
_SEV = {
    "crit": ("●", "bold red"),
    "warn": ("▲", "bold yellow"),
    "info": ("·", "cyan"),
}
_RECENT_SAMPLES = 240


def _util_color(pct: float) -> str:
    return "green" if pct < 60 else ("yellow" if pct < 85 else "red")


def _buckets(seq, n: int) -> List[list]:
    """Split a sequence into n contiguous near-equal buckets.

    Lets a long history window be shown in a fixed display width: each column
    summarizes a slice of time rather than a single sample.
    """
    seq = list(seq)
    if not seq or n <= 0:
        return []
    if len(seq) <= n:
        return [[x] for x in seq]
    L = len(seq)
    return [seq[i * L // n:(i + 1) * L // n] or [seq[min(i * L // n, L - 1)]] for i in range(n)]


def sparkline(values, width: int = 28) -> Text:
    t = Text()
    for b in _buckets(values, width):
        v = sum(b) / len(b)
        idx = max(0, min(7, int(round((v / 100.0) * 7))))
        t.append(_SPARK[idx], style=_util_color(v))
    return t


def owner_colors(owners) -> dict:
    """Map distinct project names to palette colors, sorted for stability."""
    names = sorted({o for o in owners if o})
    return {n: _PALETTE[i % len(_PALETTE)] for i, n in enumerate(names)}


def ownership_strip(util, owner, colors: dict, width: int = 28) -> Text:
    """One block per time-bucket, colored by the project that owned it.

    Per bucket the dominant owner among active samples wins; a bucket that was
    mostly idle renders grey.
    """
    ub = _buckets(util, width)
    ob = _buckets(owner, width)
    t = Text()
    for u_b, o_b in zip(ub, ob):
        avg = sum(u_b) / len(u_b)
        owners = [o for o, uu in zip(o_b, u_b) if o and uu >= _IDLE_UTIL]
        own = Counter(owners).most_common(1)[0][0] if owners else None
        if avg < _IDLE_UTIL or not own:
            t.append("█", style="grey30")
        else:
            t.append("█", style=colors.get(own, "white"))
    return t


def ownership_legend(colors: dict) -> Text:
    if not colors:
        return Text("(idle)", style="grey50")
    t = Text()
    for name, c in colors.items():
        t.append("█ ", style=c)
        t.append(f"{name}  ", style="grey74")
    return t


_LOG_SEGMENTS = [
    (24 * 60 * 60, 12 * 60 * 60, 16, "-24h"),
    (12 * 60 * 60, 60 * 60, 28, "-12h"),
    (60 * 60, 60, 32, "-1h"),
    (60, 0, 20, "-1m"),
]


def _scaled_segment_widths(width: int) -> List[int]:
    base = [seg[2] for seg in _LOG_SEGMENTS]
    total = sum(base)
    widths = [max(1, int(round(width * n / total))) for n in base]
    delta = width - sum(widths)
    widths[-1] += delta
    if widths[-1] < 1:
        widths[-1] = 1
    return widths


def _time_buckets(times, values, width: int = 96, now: float | None = None) -> List[float | None]:
    """Log-ish time buckets: 24h->12h->1h->1m->now."""
    pairs = [(float(t), float(v)) for t, v in zip(times, values)]
    if not pairs:
        return []
    now = max(t for t, _ in pairs) if now is None else now
    widths = _scaled_segment_widths(width)
    buckets: List[float | None] = []
    idx = 0
    pairs.sort()
    for (older, newer, _, _), count in zip(_LOG_SEGMENTS, widths):
        segment_start = now - older
        segment_end = now - newer
        step = (segment_end - segment_start) / count
        for i in range(count):
            start = segment_start + i * step
            end = segment_start + (i + 1) * step
            while idx < len(pairs) and pairs[idx][0] < start:
                idx += 1
            j = idx
            vals = []
            while j < len(pairs) and pairs[j][0] < end:
                vals.append(pairs[j][1])
                j += 1
            buckets.append(sum(vals) / len(vals) if vals else None)
    return buckets


def usage_bar_chart(values, width: int = 96, times=None) -> List[Text]:
    """Render a compact percent-axis area chart for utilization history."""
    if times:
        avgs = _time_buckets(times, values, width=width)
    else:
        avgs = [sum(b) / len(b) for b in _buckets(values, width)]
    rows: List[Text] = []
    for level in range(100, 0, -10):
        row = Text(f"{level:>3}% │", style="grey62")
        threshold = max(0, level - 10)
        for v in avgs:
            if v is None:
                row.append(" ", style="")
            else:
                row.append("█" if v > threshold else " ", style=_util_color(v) if v > threshold else "")
        rows.append(row)
    axis = Text("  0% └", style="grey62")
    axis.append("─" * max(1, len(avgs)), style="grey37")
    rows.append(axis)
    return rows


def timeline_axis(values, interval: float, width: int = 96, times=None) -> Text:
    """Label the time range under the history chart.

    The chart is bucketed, so per-column timestamps would be noisy. Mark the
    left edge as "how far back this visible history starts" and the right edge
    as now.
    """
    if times:
        bucket_count = len(_time_buckets(times, values, width=width))
    else:
        bucket_count = len(_buckets(values, width))
    if not bucket_count:
        return Text("      no samples yet", style="grey62")

    if times:
        widths = _scaled_segment_widths(width)
        labels = ["-24h", "-12h", "-1h", "-1m", "now"]
        positions = [0]
        acc = 0
        for w in widths[:-1]:
            acc += w
            positions.append(acc)
        positions.append(bucket_count - len(labels[-1]))
        chars = [" "] * bucket_count
        occupied = [False] * bucket_count
        for label, pos in zip(labels, positions):
            pos = max(0, min(bucket_count - len(label), pos))
            if any(occupied[pos:pos + len(label)]):
                continue
            for offset, ch in enumerate(label):
                chars[pos + offset] = ch
                occupied[pos + offset] = True
        axis = Text("      ", style="grey62")
        axis.append("".join(chars), style="grey74")
        return axis

    shown = human_duration(len(values) * interval)
    left = f"-{shown} ago"
    right = "now"
    gap = max(1, bucket_count - len(left) - len(right))
    axis = Text("      ", style="grey62")
    axis.append(left, style="grey74")
    axis.append(" " * gap, style="grey37")
    axis.append(right, style="grey74")
    return axis


def gauge(label: str, pct, width: int = 13, detail: str | None = None) -> Text:
    pct = max(0.0, min(100.0, pct or 0.0))
    filled = int(round(pct / 100.0 * width))
    color = _util_color(pct)
    t = Text()
    t.append(f"{label:<10}", style="bold")
    t.append("█" * filled, style=color)
    t.append("─" * (width - filled), style="grey37")
    t.append(f" {pct:5.1f}%", style=color)
    if detail:
        t.append(f"  {detail}", style="grey62")
    return t


def _header(static: StaticInfo, stats: GpuStats) -> Panel:
    left = Text()
    left.append("◣◢ ", style="bold cyan")
    left.append("sonar", style="bold white")
    left.append("  GPU monitor", style="grey62")

    spec = Text()
    spec.append(static.gpu_name, style="bold")
    if static.cores:
        spec.append(f"  {static.cores} cores", style="grey62")
    if static.gpu_count > 1:
        spec.append(f"  ×{static.gpu_count}", style="grey62")
    spec.append(f"  {static.platform}", style="grey62")
    spec.append(f"  ·  {static.backend}", style="cyan")

    extra = Text()
    if stats.power_w is not None:
        extra.append(f"  {stats.power_w:.0f}W", style="magenta")
    if stats.temp_c is not None:
        extra.append(f"  {stats.temp_c:.0f}°C", style="red")
    extra.append(f"   {time.strftime('%H:%M:%S')}", style="grey62")

    grid = Table.grid(expand=True)
    grid.add_column(justify="left")
    grid.add_column(justify="right")
    grid.add_row(left, Text.assemble(spec, extra))
    return Panel(grid, box=ROUNDED, border_style="cyan", padding=(0, 1))


def _gauges_panel(stats: GpuStats, history) -> Panel:
    recent_util = list(history.util)[-_RECENT_SAMPLES:]
    recent_owner = list(history.owner)[-_RECENT_SAMPLES:]
    lines: List[Text] = [gauge("GPU", stats.device_util)]
    if stats.renderer_util is not None:
        lines.append(gauge("Renderer", stats.renderer_util))
    if stats.tiler_util is not None:
        lines.append(gauge("Tiler", stats.tiler_util))

    if stats.mem_used is not None and stats.mem_total:
        mem_pct = stats.mem_used / stats.mem_total * 100
        lines.append(gauge("Memory", mem_pct, detail=f"{human_bytes(stats.mem_used)}/{human_bytes(stats.mem_total)}"))

    lines.append(Text(""))
    trend = Text(f"{'Util':<10}", style="bold")
    trend.append_text(sparkline(recent_util))
    lines.append(trend)

    # Ownership strip: which project held the GPU at each point in the window.
    colors = owner_colors(recent_owner)
    strip = Text(f"{'Owner':<10}", style="bold")
    strip.append_text(ownership_strip(recent_util, recent_owner, colors))
    lines.append(strip)
    legend = Text(" " * 10)
    legend.append_text(ownership_legend(colors))
    lines.append(legend)

    return Panel(Group(*lines), title="[bold]load[/]", title_align="left",
                 box=ROUNDED, border_style="grey50", padding=(1, 1))


def _history_panel(history, interval: float, width: int = 96) -> Panel:
    values = list(history.util)
    times = list(getattr(history, "ts", []))
    maxlen = getattr(history.util, "maxlen", None)
    window = human_duration(maxlen * interval) if maxlen else human_duration(len(values) * interval)
    if values:
        avg = sum(values) / len(values)
        active = sum(1 for v in values if v >= _IDLE_UTIL)
        active_pct = active / len(values) * 100
        if times and len(times) >= 2:
            collected = human_duration(max(0.0, times[-1] - times[0]))
        else:
            collected = human_duration(len(values) * interval)
    else:
        avg = 0.0
        active_pct = 0.0
        collected = "0s"

    chart = usage_bar_chart(values, width=width, times=times)
    chart.append(timeline_axis(values, interval, width=width, times=times))
    stats = Text(" " * 10, style="")
    stats.append("showing last ", style="grey62")
    stats.append(collected, style="grey74")
    if collected != window:
        stats.append(" of ", style="grey62")
        stats.append(window, style="grey74")
    stats.append("   avg ", style="grey62")
    stats.append(f"{avg:.0f}%", style=_util_color(avg))
    if values:
        stats.append("   min/max/latest ", style="grey62")
        stats.append(f"{min(values):.0f}/{max(values):.0f}/{values[-1]:.0f}%", style="grey74")
    stats.append("   active ", style="grey62")
    stats.append(f"{active_pct:.0f}%", style="bold green" if active_pct >= 50 else "grey74")
    stats.append("   oldest → newest", style="grey62")
    return Panel(Group(*chart, stats), title="[bold]GPU usage timeline[/]", title_align="left",
                 box=ROUNDED, border_style="grey50", padding=(0, 1))


def _hints_panel(hints: List[Hint]) -> Panel:
    lines: List[Text] = []
    for h in hints:
        icon, style = _SEV.get(h.severity, ("·", "white"))
        t = Text()
        t.append(f" {icon} ", style=style)
        t.append(h.text)
        lines.append(t)
    return Panel(Group(*lines), title="[bold]hints[/]", title_align="left",
                 box=ROUNDED, border_style="grey50", padding=(0, 1))


def _process_table(procs: List[ProcInfo]) -> Panel:
    show_gpu_mem = any(p.gpu_mem is not None for p in procs)
    table = Table(box=ROUNDED, expand=True, border_style="grey37",
                  header_style="bold grey74", pad_edge=False)
    table.add_column("PID", justify="right", style="grey62", no_wrap=True)
    table.add_column("PROJECT", style="bold cyan", no_wrap=True)
    table.add_column("COMMAND", style="white", no_wrap=True, overflow="ellipsis", ratio=1)
    table.add_column("CPU%", justify="right", no_wrap=True)
    table.add_column("RSS", justify="right", style="grey62", no_wrap=True)
    if show_gpu_mem:
        table.add_column("GPU MEM", justify="right", style="magenta", no_wrap=True)
    table.add_column("TIME", justify="right", style="grey62", no_wrap=True)

    if not procs:
        table.add_row("—", "—", "no GPU-run processes detected", "", "", *(["" ] if show_gpu_mem else []), "")
    for i, p in enumerate(procs):
        cpu_style = "green" if p.cpu < 50 else ("yellow" if p.cpu < 100 else "red")
        row_style = "on grey15" if i == 0 else None
        cells = [
            str(p.pid),
            p.project or "—",
            p.cmd or p.name,
            Text(f"{p.cpu:.0f}", style=cpu_style),
            human_bytes(p.rss),
        ]
        if show_gpu_mem:
            cells.append(human_bytes(p.gpu_mem) if p.gpu_mem is not None else "—")
        cells.append(p.etime or "—")
        table.add_row(*cells, style=row_style)

    return Panel(table, title="[bold]processes  (GPU-run focus)[/]",
                 title_align="left", box=ROUNDED, border_style="grey50", padding=(0, 0))


def _job_label(job: GpuqJob) -> str:
    label = job.name or job.id
    return label if len(label) <= 32 else label[:31] + "…"


def _dur_short(seconds) -> str:
    if seconds is None:
        return "—"
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{max(1, round(s / 60))}m"
    if s < 86400:
        h, rem = divmod(s, 3600)
        return f"{h}h{round(rem / 60):02d}m"
    d, rem = divmod(s, 86400)
    return f"{d}d{round(rem / 3600)}h"


def _clock_after(seconds) -> str:
    if seconds is None:
        return "—"
    return time.strftime("%H:%M", time.localtime(time.time() + max(0, seconds)))


def _progress(job: GpuqJob) -> str:
    if job.progress_current is None:
        return "—"
    if job.progress_total:
        pct = job.progress_current / max(1, job.progress_total) * 100
        prefix = f"{job.progress_label} " if job.progress_label else ""
        return f"{prefix}{job.progress_current}/{job.progress_total} {pct:.0f}%"
    prefix = f"{job.progress_label} " if job.progress_label else ""
    return f"{prefix}{job.progress_current}"


def _gpuq_panel(gpuq: GpuqSnapshot | None, max_lines: int | None = None) -> Panel:
    lines: List[Text] = []
    if gpuq is None or not gpuq.available:
        lines.append(Text("gpuq state not found", style="grey62"))
    elif gpuq.error:
        lines.append(Text(gpuq.error, style="red"))
    else:
        if gpuq.running:
            job = gpuq.running
            label = Text()
            label.append("run ", style="bold green")
            if job.project:
                label.append(f"{job.project} · ", style="bold cyan")
            label.append(_job_label(job), style="grey74")
            lines.append(label)

            timing = Text("  ", style="")
            timing.append(_progress(job), style="grey74")
            timing.append("  elapsed ", style="grey62")
            timing.append(_dur_short(job.elapsed_seconds), style="grey74")
            if job.eta_seconds is not None:
                total = (job.elapsed_seconds or 0) + job.eta_seconds
                timing.append("  done ~", style="grey62")
                timing.append(_clock_after(job.eta_seconds), style="bold yellow")
                timing.append(" (", style="grey62")
                timing.append(_dur_short(job.eta_seconds), style="yellow")
                timing.append(")", style="grey62")
            else:
                timing.append("  done —", style="grey50")
            lines.append(timing)
        if not gpuq.running and not gpuq.queued:
            state = "paused" if gpuq.paused else "free"
            lines.append(Text(f"{state} · queue empty", style="yellow" if gpuq.paused else "grey62"))
        queued_start_after = gpuq.running.eta_seconds if gpuq.running else 0.0
        queue = gpuq.queued
        # One compact row per queued job. When the panel can't fit them all,
        # show as many as fit and collapse the rest into a "+N more" line so the
        # count in the title always matches what's on screen (rich would
        # otherwise silently crop the overflow).
        budget = len(queue) if max_lines is None else max(0, max_lines - len(lines))
        overflow = max(0, len(queue) - budget)
        if overflow:
            budget = max(0, budget - 1)  # reserve a line for the "+N more" note
            overflow = len(queue) - budget
        for index, job in enumerate(queue[:budget], start=1):
            row = Text()
            row.append(f"q{index} ", style="grey62")
            if job.project:
                row.append(f"{job.project} · ", style="bold cyan")
            row.append(_job_label(job), style="grey74")
            if job.priority is not None:
                row.append("  prio ", style="grey62")
                row.append(str(job.priority), style="bold grey74")
            if queued_start_after is not None:
                row.append("  starts ~", style="grey62")
                row.append(_clock_after(queued_start_after), style="yellow")
                if job.eta_seconds is not None:
                    row.append(" → done ~", style="grey62")
                    row.append(_clock_after(queued_start_after + job.eta_seconds), style="yellow")
                    queued_start_after += job.eta_seconds
                else:
                    queued_start_after = None
            elif gpuq.running:
                row.append("  waits for prior jobs", style="grey50")
            else:
                row.append("  waits for lease", style="grey50")
            if job.progress_total:
                row.append(f"  {job.progress_total} steps", style="grey62")
            lines.append(row)
        if overflow > 0:
            more = Text("   … +", style="grey50")
            more.append(str(overflow), style="bold grey62")
            more.append(" more queued", style="grey50")
            lines.append(more)

    title = "[bold]gpuq queue[/]"
    if gpuq and gpuq.available and not gpuq.error:
        title += f"  [grey62]{len(gpuq.queued)} queued[/]"
        if gpuq.queued and gpuq.running and gpuq.running.eta_seconds is not None:
            first = gpuq.queued[0]
            start = gpuq.running.eta_seconds
            if first.eta_seconds is not None:
                title += (
                    f"  [yellow]q1 {_clock_after(start)}"
                    f"→{_clock_after(start + first.eta_seconds)}[/]"
                )
            else:
                title += f"  [yellow]q1 starts {_clock_after(start)}[/]"
    return Panel(Group(*lines), title=title, title_align="left",
                 box=ROUNDED, border_style="grey50", padding=(0, 0))


def render(static: StaticInfo, stats: GpuStats, procs: List[ProcInfo],
           hints: List[Hint], history, interval: float,
           gpuq: GpuqSnapshot | None = None) -> Layout:
    root = Layout()
    root.split_column(
        Layout(name="header", size=3),
        Layout(name="body"),
        Layout(name="timeline", size=15),
        Layout(name="footer", size=1),
    )
    root["body"].split_row(
        Layout(name="left", ratio=2, minimum_size=42),
        Layout(name="right", ratio=3),
    )
    root["left"].split_column(
        Layout(_gauges_panel(stats, history), name="gauges", size=10),
        Layout(_hints_panel(hints), name="hints"),
    )
    root["header"].update(_header(static, stats))
    try:
        term_h = Console().size.height
    except Exception:
        term_h = 40
    right_h = max(10, term_h - 3 - 15 - 1)  # right column height: minus header, timeline, footer
    running_lines = 1
    n_queued = 0
    if gpuq is not None and gpuq.available and not gpuq.error:
        if gpuq.running:
            running_lines = 2
        elif not gpuq.queued:
            running_lines = 1
        else:
            running_lines = 0
        n_queued = len(gpuq.queued)
    # Grow the queue panel to fit all jobs, but keep the process table alive and
    # never drop below the old default height (baseline) on normal terminals.
    need = running_lines + n_queued
    proc_min = 4
    baseline = min(need, 6)
    avail = max(3, right_h - proc_min - 2)  # 2 = gpuq panel borders
    gpuq_interior = max(baseline, min(need, avail))
    root["right"].split_column(
        Layout(_process_table(procs), name="processes", ratio=3),
        Layout(_gpuq_panel(gpuq, max_lines=gpuq_interior), name="gpuq", size=gpuq_interior + 2),
    )
    root["timeline"].update(_history_panel(history, interval))
    footer = Text()
    footer.append("  q", style="bold cyan")
    footer.append(" quit   ", style="grey62")
    footer.append("ctrl-c", style="bold cyan")
    footer.append(" quit   ", style="grey62")
    footer.append(f"refresh {interval:g}s", style="grey62")
    maxlen = getattr(history.util, "maxlen", None)
    if maxlen:
        footer.append(f"   window ~{human_duration(maxlen * interval)}", style="grey62")
    root["footer"].update(Align.left(footer))
    return root


def render_report(summary, source: str):
    """Render a report.Summary as a per-project table plus a totals line."""
    colors = owner_colors([p.project for p in summary.projects])
    table = Table(box=ROUNDED, expand=False, border_style="grey37",
                  header_style="bold grey74", title=f"GPU ownership · {source}",
                  title_style="bold cyan")
    table.add_column("PROJECT", style="bold")
    table.add_column("GPU TIME", justify="right")
    table.add_column("% ACTIVE", justify="right")
    table.add_column("SHARE", justify="left", no_wrap=True)

    active = summary.active_seconds or 1.0
    for p in summary.projects:
        pct = p.seconds / active * 100
        bar_w = max(1, int(round(pct / 100 * 24)))
        bar = Text("█" * bar_w, style=colors.get(p.project, "white"))
        table.add_row(
            Text(p.project, style=colors.get(p.project, "white")),
            human_duration(p.seconds),
            f"{pct:.0f}%",
            bar,
        )
    if not summary.projects:
        table.add_row("—", "—", "—", "")

    span = summary.span_seconds or 1.0
    idle_pct = summary.idle_seconds / span * 100
    totals = Text()
    totals.append("  span ", style="grey62")
    totals.append(human_duration(summary.span_seconds), style="bold")
    totals.append("   active ", style="grey62")
    totals.append(human_duration(summary.active_seconds), style="bold green")
    totals.append("   idle ", style="grey62")
    totals.append(f"{human_duration(summary.idle_seconds)} ({idle_pct:.0f}%)",
                  style="bold yellow" if idle_pct > 25 else "bold")
    totals.append("   avg util ", style="grey62")
    totals.append(f"{summary.avg_util:.0f}%", style="bold")
    totals.append(f"   {summary.samples} samples", style="grey62")
    return Group(table, totals)
