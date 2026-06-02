from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import SynthesisResult


class PiperEngine:
    name = "piper"

    def synthesize(self, *, text: str, output_path: Path, payload: dict[str, Any]) -> SynthesisResult:
        raise RuntimeError("Piper engine is not installed/configured yet. Install Piper before enabling ultrafast mode.")
