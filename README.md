# sonar

[![ci](https://github.com/Sushil-Thapa/sonar/actions/workflows/ci.yml/badge.svg)](https://github.com/Sushil-Thapa/sonar/actions/workflows/ci.yml)

A small GPU monitor TUI. A nerfed `nvidia-smi`/`htop` for the GPU that also tells you
**which project folder** is driving the load and **how to optimize**.

- **macOS (Apple Silicon / MLX)** — global GPU utilization, renderer/tiler, and unified
  memory from `ioreg` (no sudo).
- **Linux (NVIDIA)** — utilization, VRAM, temperature, power, and **real per-process GPU
  memory** from `nvidia-smi` (no sudo).

![sonar screenshot](https://raw.githubusercontent.com/Sushil-Thapa/sonar/main/docs/screenshot.svg)

The **Util** sparkline and **Owner** strip read left-to-right over the recent window:
above, `monorepo/alpha` (cyan) held the GPU, went idle (grey), then handed off to
`monorepo/beta` (magenta). The bottom **GPU usage timeline** is a percent-axis bar chart
over the full retained window, 24 hours by default, so long runs and overnight idle gaps
are visible at a glance. Its x-axis is log-ish (`-24h`, `-12h`, `-1h`, `-1m`, `now`):
recent minutes get more visual resolution while the overnight picture stays visible. Live
history is saved to `~/.sonar/history-24h.jsonl` by default and reloaded on restart; while
sonar is still warming up, the stats line says how much of the 24-hour window has actually
been collected.
Regenerate the image with `python scripts/gen_screenshot.py`.

## The honest caveat

macOS exposes **no public per-process GPU API** (Activity Monitor uses private ones). So
the macOS process table attributes the *global* GPU number to the dominant compute process
and the folder it runs from. To keep the panel useful, macOS only surfaces likely GPU-run
workloads such as Python/ML runtimes and model/training commands. Assistant shells such as
Claude, Codex, and ChatGPT are hidden by default; if they launch real GPU work, the child
Python/model process is what should show. This is accurate when you run one GPU job at a
time. On NVIDIA, per-process GPU memory is real (from `nvidia-smi`).

"Which folder" = the process's working directory resolved to its git repo (plus one level,
so a monorepo like `~/code/monorepo` stays split into `monorepo/alpha`, `monorepo/beta`, …).

The table shows **both** the folder and the actual command line (`python train.py --config
…`). The folder is the grouping/attribution key — it drives the owner strip and `report` —
while the command line is the detail that tells you *what* within that project is running.

## Install

**Recommended — uv tool** (puts a global `sonar` on your PATH, isolated env):

```sh
uv tool install .            # from the repo dir; or: uv tool install /path/to/sonar
sonar                        # now works from any directory
uv tool upgrade sonar        # after pulling changes
```

**Ephemeral — uvx** (run without installing):

```sh
uvx --from . sonar           # or: uvx --from /path/to/sonar sonar report
```

**Project venv — uv sync / pip** (for development):

```sh
uv sync                      # then: uv run sonar
# or: python3 -m venv .venv && .venv/bin/pip install -e . && .venv/bin/sonar
```

If `sonar` isn't found after `uv tool install`, run `uv tool update-shell` once and open a
new terminal (adds `~/.local/bin` to PATH).

## Usage

```sh
sonar                 # live TUI, refresh every 1.5s   (q or ctrl-c to quit)
sonar -i 0.5          # faster refresh
sonar --once          # render one frame and exit (good for screenshots / cron)
sonar --json          # one machine-readable sample, then exit
sonar --log           # also append report samples to ~/.sonar/log-DATE.jsonl
sonar --no-persist    # don't reload/save the rolling 24h live timeline
sonar --cpu-threshold 10   # legacy Apple heuristic threshold; GPU-run focus stays on
sonar --window 480         # override retained samples (default: 24h at refresh interval)
sonar --power              # macOS: GPU watts via passwordless `sudo powermetrics`

sonar report          # roll up today's log: GPU time per project + idle
sonar report --date 2026-06-13
sonar report path/to/log.jsonl
```

## Ownership timeline

The live dashboard has an **Owner strip** under the utilization sparkline: one block per
sample, colored by the project that held the GPU at that moment (grey = idle), with a
legend. It shows handoffs and idle gaps at a glance — "alpha held it, then a gap, then beta".
The full-width bottom chart shows GPU utilization across the retained window with 10% visual
bands and exact min/max/latest percentages in the stats line. With the default refresh interval
it keeps roughly 57,600 samples, or 24 hours, and buckets them into compact bars so you can tell
whether the GPU stayed fed during a long run. The x-axis is relative and non-linear: `-24h`,
`-12h`, `-1h`, `-1m`, `now`. That keeps recent spikes readable without losing the overnight
view. The rolling live cache is `~/.sonar/history-24h.jsonl`; it is pruned back to the retained
window when sonar closes or restarts.

For the retrospective, `sonar report` reads the JSONL log and prints a per-project rollup:
GPU time, % of active time, a share bar, and a totals line (span, active, **idle %**, avg
util). On a single GPU run serially, the idle number is the one to watch — it's the time
the scarce GPU sat unused between runs. (A full multi-lane Gantt is intentionally skipped:
with serial runs only one lane is ever active, so the strip + rollup carry the signal.)

The JSONL log records util, memory, and the owning project/PID per sample. The rolling live
cache is for the dashboard; `--log` is still useful when you want durable per-day `sonar report`
rollups.

## Remote hosts

sonar can also surface remote cluster GPUs beside the local queue. Drop one status snapshot
per host into `~/.gpuq/remote/*.json` (or `$GPUQ_HOME/remote/`) and sonar renders each under
the gpuq panel. For a reachable node it shows one line per GPU: utilization (same
green/yellow/red thresholds as the local gauges), memory, and the user and job holding it.
Unreachable nodes fall back to the scheduler's allocation list. sonar only reads these files,
re-reading them every frame, and flags any snapshot older than 30 minutes as `STALE`. When the
directory is empty nothing renders, so local-only users pay nothing for the feature.

Some out-of-band probe writes the files (sonar never does). Every key is optional, and older
files without `host_status` still render:

```json
{
  "ts": 1700000000,
  "host": "cluster1",
  "du": "9.5G",
  "jobs": [{"id": "1", "state": "RUNNING", "name": "train-run", "elapsed": "2:00", "gres": "gres:gpu:1", "node": "node-a"}],
  "host_status": {
    "allocs": [{"user": "alice", "node": "node-a", "gres": "gres:gpu:1", "state": "RUNNING", "jobname": "train-run", "elapsed": "2:00"}],
    "nodes": {
      "node-a": {"reachable": true, "gpus": [{"i": 0, "util_pct": 90, "mem_used_mib": 12000, "mem_total_mib": 24000, "users": ["alice"]}]},
      "node-b": {"reachable": false, "gpus": []}
    }
  }
}
```

## Hints

Rule-based flags over the current sample plus recent history:

- **memory pressure** — usage near the unified-RAM / VRAM ceiling (OOM risk).
- **co-resident runs** — ≥2 GPU processes at once (breaks a serial single-GPU policy).
- **stall / input-bound** — a run is alive but the GPU has been idle for several samples.
- **underutilized** — sustained low utilization during a run (batch size / data pipeline).
- **unattributed load** — GPU busy but no compute process matched (lower `--cpu-threshold`).

## Layout

```
sonar/
  backends/        # the OS seam: base.py interface, apple.py (ioreg), nvidia.py (nvidia-smi)
  model.py         # shared dataclasses (StaticInfo, GpuStats, ProcInfo, Hint)
  util.py          # command runner, byte formatting, cwd→project mapping
  history.py       # rolling buffers (util + owner) + optional JSONL logging
  gpuq.py          # read-only reader for local scheduler/gpuq state
  remote.py        # read-only reader for remote host snapshots (<gpuq-home>/remote/*.json)
  hints.py         # pure rule engine
  report.py        # pure log rollup: per-project GPU time + idle
  ui.py            # Rich Live rendering (dashboard + report)
  cli.py           # args, live loop, snapshot/JSON modes, report subcommand
tests/             # parsers tested against captured command fixtures (no GPU needed)
```

Every OS command is wrapped in a pure parser (text in → dataclasses out), so the
GPU-specific logic is unit-tested with fixtures on any machine: `.venv/bin/pytest`.
