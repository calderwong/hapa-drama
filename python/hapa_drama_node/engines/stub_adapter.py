from __future__ import annotations

import math
import wave
from pathlib import Path
from typing import Any

from .base import SynthesisResult


class StubDramaEngine:
    name = "stub"

    def synthesize(self, *, text: str, output_path: Path, payload: dict[str, Any]) -> SynthesisResult:
        sample_rate = 22050
        duration_seconds = min(3.0, max(0.35, len(text) / 42.0))
        frequency = 220.0 + (sum(text.encode("utf-8")) % 220)
        total_samples = int(sample_rate * duration_seconds)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output_path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sample_rate)
            for idx in range(total_samples):
                envelope = min(1.0, idx / max(1, sample_rate * 0.05), (total_samples - idx) / max(1, sample_rate * 0.05))
                value = int(0.20 * envelope * 32767 * math.sin(2 * math.pi * frequency * idx / sample_rate))
                w.writeframesraw(value.to_bytes(2, byteorder="little", signed=True))
        return SynthesisResult(
            engine=self.name,
            audio_path=output_path,
            duration_seconds=duration_seconds,
            sample_rate=sample_rate,
            metadata={"stub": True, "frequency": frequency},
        )
