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
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .model import GpuStats, Hint, ProcInfo, StaticInfo
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


def gauge(label: str, pct, width: int = 18) -> Text:
    pct = max(0.0, min(100.0, pct or 0.0))
    filled = int(round(pct / 100.0 * width))
    color = _util_color(pct)
    t = Text()
    t.append(f"{label:<10}", style="bold")
    t.append("█" * filled, style=color)
    t.append("─" * (width - filled), style="grey37")
    t.append(f" {pct:5.1f}%", style=color)
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
    lines: List[Text] = [gauge("GPU", stats.device_util)]
    if stats.renderer_util is not None:
        lines.append(gauge("Renderer", stats.renderer_util))
    if stats.tiler_util is not None:
        lines.append(gauge("Tiler", stats.tiler_util))

    if stats.mem_used is not None and stats.mem_total:
        mem_pct = stats.mem_used / stats.mem_total * 100
        lines.append(gauge("Memory", mem_pct))
        cap = Text()
        cap.append("           ", style="")
        cap.append(f"{human_bytes(stats.mem_used)} / {human_bytes(stats.mem_total)}", style="grey62")
        lines.append(cap)

    lines.append(Text(""))
    trend = Text(f"{'Util':<10}", style="bold")
    trend.append_text(sparkline(history.util))
    lines.append(trend)

    # Ownership strip: which project held the GPU at each point in the window.
    colors = owner_colors(history.owner)
    strip = Text(f"{'Owner':<10}", style="bold")
    strip.append_text(ownership_strip(history.util, history.owner, colors))
    lines.append(strip)
    legend = Text(" " * 10)
    legend.append_text(ownership_legend(colors))
    lines.append(legend)

    return Panel(Group(*lines), title="[bold]load[/]", title_align="left",
                 box=ROUNDED, border_style="grey50", padding=(1, 1))


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
        table.add_row("—", "—", "no compute processes detected", "", "", *(["" ] if show_gpu_mem else []), "")
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

    return Panel(table, title="[bold]processes  (by dominant compute)[/]",
                 title_align="left", box=ROUNDED, border_style="grey50", padding=(0, 0))


def render(static: StaticInfo, stats: GpuStats, procs: List[ProcInfo],
           hints: List[Hint], history, interval: float) -> Layout:
    root = Layout()
    root.split_column(
        Layout(name="header", size=3),
        Layout(name="body"),
        Layout(name="footer", size=1),
    )
    root["body"].split_row(
        Layout(name="left", ratio=2, minimum_size=42),
        Layout(name="right", ratio=3),
    )
    root["left"].split_column(
        Layout(_gauges_panel(stats, history), name="gauges"),
        Layout(_hints_panel(hints), name="hints"),
    )
    root["header"].update(_header(static, stats))
    root["right"].update(_process_table(procs))
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
