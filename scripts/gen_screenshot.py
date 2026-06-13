#!/usr/bin/env python3
"""Render a representative sonar frame to docs/screenshot.svg.

Uses synthetic-but-realistic state so the image is stable and doesn't depend on
whatever happens to be running. Re-run after UI changes:

    python scripts/gen_screenshot.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rich.console import Console  # noqa: E402

from sonar import ui  # noqa: E402
from sonar.history import History  # noqa: E402
from sonar.hints import evaluate  # noqa: E402
from sonar.model import GpuStats, Hint, ProcInfo, StaticInfo  # noqa: E402

GB = 1024 ** 3


def fake_history() -> History:
    h = History(maxlen=120)
    # A handoff: alpha ran, a short idle gap, then beta ramps up to full.
    for i in range(120):
        if i < 55:
            util, owner = 96, "monorepo/alpha"
        elif i < 67:
            util, owner = 2, None                 # idle gap between runs
        else:
            util, owner = 88 + (i % 6), "monorepo/beta"
        h.util.append(util)
        h.mem.append(int(28 * GB))
        h.owner.append(owner)
    return h


def main() -> None:
    static = StaticInfo(backend="apple", gpu_name="Apple M4 Pro", cores=16,
                        mem_total=48 * GB, platform="macOS")
    stats = GpuStats(device_util=92.0, renderer_util=61.0, tiler_util=44.0,
                     mem_used=int(31 * GB), mem_total=48 * GB)
    procs = [
        ProcInfo(pid=50286, name="python3", cmd="python3 train.py --config c.yaml",
                 cpu=312.0, rss=int(28 * GB), etime="01:42:10", project="monorepo/beta", is_gpu=True),
        ProcInfo(pid=49001, name="python3", cmd="python3 eval.py --split val",
                 cpu=8.0, rss=int(2 * GB), etime="00:03:55", project="monorepo/alpha", is_gpu=True),
        ProcInfo(pid=512, name="WindowServer", cmd="WindowServer", cpu=23.0,
                 rss=int(0.4 * GB), etime="11:20:03", project=None, is_gpu=False),
    ]
    hist = fake_history()
    hints = evaluate(static, stats, procs, hist.util) or [Hint("info", "GPU healthy.")]

    console = Console(record=True, width=118, height=34)
    console.print(ui.render(static, stats, procs, hints, hist, interval=1.5))

    out = os.path.join(os.path.dirname(__file__), "..", "docs", "screenshot.svg")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    console.save_svg(out, title="sonar")
    print(f"wrote {os.path.normpath(out)}")


if __name__ == "__main__":
    main()
