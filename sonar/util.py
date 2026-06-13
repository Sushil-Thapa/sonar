"""Small helpers: running commands safely, formatting, and folder mapping."""

from __future__ import annotations

import os
import shutil
import subprocess


def run(cmd, timeout: float = 4.0) -> str:
    """Run a command, returning stdout or "" on any failure.

    A monitor must never crash because a sampled command hiccuped, so every
    failure mode (missing binary, timeout, non-zero exit) collapses to "".
    """
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return out.stdout
    except Exception:
        return ""


def have(binname: str) -> bool:
    return shutil.which(binname) is not None


def human_bytes(n) -> str:
    if n is None:
        return "-"
    f = float(n)
    for unit in ("B", "K", "M", "G", "T"):
        if f < 1024.0 or unit == "T":
            return f"{int(f)}{unit}" if unit == "B" else f"{f:.1f}{unit}"
        f /= 1024.0
    return f"{f:.1f}T"


def exe_basename(args: str) -> str:
    """Executable name from a full command line (first token's basename).

    Used for precise matching ("is this python/mlx/ollama?") rather than
    matching against the whole arg string, which would over-match on paths.
    """
    toks = args.split()
    return os.path.basename(toks[0]) if toks else ""


def short_command(args: str, cap: int = 200) -> str:
    """Compact display of a command line: interpreter path -> basename, capped.

    Turns "/path/.venv/bin/python3 train.py --config c.yaml" into
    "python3 train.py --config c.yaml" so the script and args are what show.
    """
    toks = args.split()
    if not toks:
        return args
    toks[0] = os.path.basename(toks[0])
    s = " ".join(toks)
    return s if len(s) <= cap else s[: cap - 1] + "…"


def human_duration(seconds) -> str:
    """Compact human duration: 45s, 12m, 1h23m, 2d3h."""
    if seconds is None:
        return "-"
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m{s % 60:02d}s" if s % 60 else f"{s // 60}m"
    if s < 86400:
        h, rem = divmod(s, 3600)
        return f"{h}h{rem // 60:02d}m" if rem // 60 else f"{h}h"
    d, rem = divmod(s, 86400)
    return f"{d}d{rem // 3600}h" if rem // 3600 else f"{d}d"


def find_git_root(path: str):
    p = os.path.abspath(path)
    while True:
        if os.path.isdir(os.path.join(p, ".git")):
            return p
        parent = os.path.dirname(p)
        if parent == p:
            return None
        p = parent


def project_from_cwd(cwd):
    """Map a working directory to a human-meaningful project label.

    Uses the enclosing git repo as the anchor, plus the first directory below
    it, so a monorepo like ~/code/monorepo keeps its subprojects distinct
    ("monorepo/alpha", "monorepo/beta") instead of collapsing to "monorepo".
    Falls back to the first two path segments under ~/code, then the basename.
    """
    if not cwd:
        return None
    cwd = os.path.abspath(cwd)
    git = find_git_root(cwd)
    if git:
        root = os.path.basename(git)
        rel = os.path.relpath(cwd, git)
        if rel == ".":
            return root
        return f"{root}/{rel.split(os.sep)[0]}"
    code = os.path.join(os.path.expanduser("~"), "code")
    if cwd.startswith(code + os.sep):
        rest = [s for s in cwd[len(code) + 1:].split(os.sep) if s]
        return "/".join(rest[:2]) if rest else os.path.basename(cwd)
    return os.path.basename(cwd) or cwd
