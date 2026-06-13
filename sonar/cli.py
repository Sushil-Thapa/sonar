"""Command-line entry point: argument parsing, the live loop, and snapshots."""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time

from . import hints as hints_mod
from . import ui
from .backends import detect_backend
from .history import History, default_logpath


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sonar",
        description="GPU monitor TUI for macOS (Apple/MLX) and Linux (NVIDIA).",
    )
    p.add_argument("-i", "--interval", type=float, default=1.5, help="refresh seconds (default 1.5)")
    p.add_argument("--once", action="store_true", help="render a single snapshot and exit")
    p.add_argument("--json", action="store_true", help="emit one JSON sample and exit")
    p.add_argument(
        "--log", nargs="?", const=default_logpath(), default=None,
        metavar="PATH", help="append samples as JSONL (default ~/.sonar/log-DATE.jsonl)",
    )
    p.add_argument(
        "--cpu-threshold", type=float, default=20.0,
        help="non-compute processes show only above this CPU%% (default 20)",
    )
    p.set_defaults(cmd="live")

    sub = p.add_subparsers(dest="cmd")
    rp = sub.add_parser("report", help="summarize a JSONL log into per-project GPU time")
    rp.add_argument("path", nargs="?", default=None, help="log file (default ~/.sonar/log-DATE.jsonl)")
    rp.add_argument("--date", default=None, metavar="YYYY-MM-DD", help="pick a day's log (default today)")
    return p


def _snapshot_json(static, stats, procs) -> str:
    return json.dumps(
        {
            "backend": static.backend,
            "gpu": static.gpu_name,
            "util": stats.device_util,
            "mem_used": stats.mem_used,
            "mem_total": stats.mem_total,
            "power_w": stats.power_w,
            "temp_c": stats.temp_c,
            "processes": [
                {
                    "pid": p.pid,
                    "project": p.project,
                    "name": p.name,
                    "cpu": p.cpu,
                    "rss": p.rss,
                    "gpu_mem": p.gpu_mem,
                }
                for p in procs
            ],
        },
        indent=2,
    )


def _start_key_listener(stop: dict) -> None:
    """Set stop['v'] when the user presses q; no-op on non-tty terminals."""
    if not sys.stdin.isatty():
        return
    try:
        import select
        import termios
        import tty
    except Exception:
        return

    def loop():
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            while not stop["v"]:
                r, _, _ = select.select([sys.stdin], [], [], 0.2)
                if r and sys.stdin.read(1) in ("q", "Q"):
                    stop["v"] = True
                    return
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)

    threading.Thread(target=loop, daemon=True).start()


def _run_report(args) -> int:
    import os

    from rich.console import Console

    from . import report as report_mod
    from .history import default_logpath

    if args.path:
        path = args.path
    elif args.date:
        path = os.path.join(os.path.expanduser("~/.sonar"), f"log-{args.date}.jsonl")
    else:
        path = default_logpath()

    if not os.path.exists(path):
        print(f"sonar: no log at {path} (run `sonar --log` to start recording)", file=sys.stderr)
        return 1

    summary = report_mod.summarize(report_mod.load_records(path))
    Console().print(ui.render_report(summary, os.path.basename(path)))
    return 0


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)

    if getattr(args, "cmd", "live") == "report":
        return _run_report(args)

    try:
        backend = detect_backend()
    except RuntimeError as e:
        print(f"sonar: {e}", file=sys.stderr)
        return 1

    static = backend.static_info()

    if args.json:
        stats = backend.sample()
        procs = backend.processes(cpu_threshold=args.cpu_threshold)
        print(_snapshot_json(static, stats, procs))
        return 0

    hist = History(logpath=args.log)

    if args.once:
        stats = backend.sample()
        procs = backend.processes(cpu_threshold=args.cpu_threshold)
        hist.add(stats, procs)
        hs = hints_mod.evaluate(static, stats, procs, hist.util)
        from rich.console import Console

        Console().print(ui.render(static, stats, procs, hs, hist, args.interval))
        hist.close()
        return 0

    from rich.live import Live

    stop = {"v": False}
    _start_key_listener(stop)
    try:
        with Live(screen=True, auto_refresh=False) as live:
            while not stop["v"]:
                stats = backend.sample()
                procs = backend.processes(cpu_threshold=args.cpu_threshold)
                hist.add(stats, procs)
                hs = hints_mod.evaluate(static, stats, procs, hist.util)
                live.update(ui.render(static, stats, procs, hs, hist, args.interval))
                live.refresh()
                waited = 0.0
                while waited < args.interval and not stop["v"]:
                    time.sleep(0.05)
                    waited += 0.05
    except KeyboardInterrupt:
        pass
    finally:
        hist.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
