from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class SynthesisResult:
    engine: str
    audio_path: Path
    duration_seconds: float
    sample_rate: int
    metadata: dict[str, Any]


class DramaEngine(Protocol):
    name: str

    def synthesize(self, *, text: str, output_path: Path, payload: dict[str, Any]) -> SynthesisResult:
        ...
