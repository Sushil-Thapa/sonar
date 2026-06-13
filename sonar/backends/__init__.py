"""Backend auto-detection: Apple on macOS, NVIDIA on Linux."""

from __future__ import annotations

import sys

from ..util import have
from .base import Backend


def detect_backend() -> Backend:
    if sys.platform == "darwin":
        from .apple import AppleBackend

        return AppleBackend()
    if have("nvidia-smi"):
        from .nvidia import NvidiaBackend

        return NvidiaBackend()
    raise RuntimeError(
        "no supported GPU backend found (need macOS ioreg or an NVIDIA GPU with nvidia-smi)"
    )
