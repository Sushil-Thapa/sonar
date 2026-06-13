# sonar

A small GPU monitor TUI. A nerfed `nvidia-smi`/`htop` for the GPU that also tells you
**which project folder** is driving the load and **how to optimize**.

- **macOS (Apple Silicon / MLX)** — global GPU utilization, renderer/tiler, and unified
  memory from `ioreg` (no sudo).
- **Linux (NVIDIA)** — utilization, VRAM, temperature, power, and **real per-process GPU
  memory** from `nvidia-smi` (no sudo).

```
◣◢ sonar  GPU monitor                         Apple M4 Pro  16 cores  macOS  ·  apple
┌ load ───────────────────────┐ ┌ processes (by dominant compute) ──────────────────┐
│ GPU       ████████████ 100% │ │  PID    PROJECT        COMMAND   CPU%   RSS   TIME │
│ Renderer  ██████        50% │ │ 50286   monorepo/alpha  python3    84   2.2G  1:37h │
│ Memory    ██████        19% │ └───────────────────────────────────────────────────┘
│ Utilization ▁▂▃▅▇█▇▆▅▃      │
│ Owner       ███████░░████   │  ← colored by which project owned the GPU
│             █ alpha  █ beta   │
└─────────────────────────────┘
┌ hints ──────────────────────┐
│  ▲ GPU idle while a run is alive — possible stall / data-loading bottleneck        │
└────────────────────────────────────────────────────────────────────────────────────┘
```

## The honest caveat

macOS exposes **no public per-process GPU API** (Activity Monitor uses private ones). So
the macOS process table attributes the *global* GPU number to the dominant compute process
and the folder it runs from. This is accurate when you run one GPU job at a time. On NVIDIA,
per-process GPU memory is real (from `nvidia-smi`).

"Which folder" = the process's working directory resolved to its git repo (plus one level,
so a monorepo like `~/code/monorepo` stays split into `monorepo/alpha`, `monorepo/beta`, …).

## Install

```sh
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/sonar          # or just `sonar` once the venv is active
```

## Usage

```sh
sonar                 # live TUI, refresh every 1.5s   (q or ctrl-c to quit)
sonar -i 0.5          # faster refresh
sonar --once          # render one frame and exit (good for screenshots / cron)
sonar --json          # one machine-readable sample, then exit
sonar --log           # also append samples to ~/.sonar/log-DATE.jsonl
sonar --cpu-threshold 10   # surface non-compute processes above 10% CPU too

sonar report          # roll up today's log: GPU time per project + idle
sonar report --date 2026-06-13
sonar report path/to/log.jsonl
```

## Ownership timeline

The live dashboard has an **Owner strip** under the utilization sparkline: one block per
sample, colored by the project that held the GPU at that moment (grey = idle), with a
legend. It shows handoffs and idle gaps at a glance — "alpha held it, then a gap, then beta".

For the retrospective, `sonar report` reads the JSONL log and prints a per-project rollup:
GPU time, % of active time, a share bar, and a totals line (span, active, **idle %**, avg
util). On a single GPU run serially, the idle number is the one to watch — it's the time
the scarce GPU sat unused between runs. (A full multi-lane Gantt is intentionally skipped:
with serial runs only one lane is ever active, so the strip + rollup carry the signal.)

The JSONL log records util, memory, and the owning project/PID per sample.

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
  hints.py         # pure rule engine
  report.py        # pure log rollup: per-project GPU time + idle
  ui.py            # Rich Live rendering (dashboard + report)
  cli.py           # args, live loop, snapshot/JSON modes, report subcommand
tests/             # parsers tested against captured command fixtures (no GPU needed)
```

Every OS command is wrapped in a pure parser (text in → dataclasses out), so the
GPU-specific logic is unit-tested with fixtures on any machine: `.venv/bin/pytest`.
