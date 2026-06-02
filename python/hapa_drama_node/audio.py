from __future__ import annotations

import math
import struct
import wave
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AudioInspection:
    path: Path
    duration_seconds: float
    sample_rate: int
    channels: int
    sample_width: int
    frame_count: int
    rms: float
    normalized_rms: float


def _pcm_rms(raw: bytes, sample_width: int) -> tuple[float, float]:
    if not raw:
        return 0.0, 0.0
    if sample_width == 1:
        values = (sample - 128 for sample in raw)
        max_abs = 128.0
    elif sample_width == 2:
        usable = raw[: len(raw) - (len(raw) % 2)]
        values = (sample[0] for sample in struct.iter_unpack("<h", usable))
        max_abs = 32768.0
    elif sample_width == 3:
        usable = raw[: len(raw) - (len(raw) % 3)]

        def iter_24_bit():
            for idx in range(0, len(usable), 3):
                value = int.from_bytes(usable[idx : idx + 3], byteorder="little", signed=False)
                if value & 0x800000:
                    value -= 0x1000000
                yield value

        values = iter_24_bit()
        max_abs = 8388608.0
    elif sample_width == 4:
        usable = raw[: len(raw) - (len(raw) % 4)]
        values = (sample[0] for sample in struct.iter_unpack("<i", usable))
        max_abs = 2147483648.0
    else:
        return 0.0, 0.0

    total = 0
    square_sum = 0.0
    for value in values:
        total += 1
        square_sum += float(value) * float(value)
    if total == 0:
        return 0.0, 0.0
    rms = math.sqrt(square_sum / total)
    return rms, min(1.0, rms / max_abs)


def inspect_wav(path: str | Path) -> AudioInspection:
    audio_path = Path(path).expanduser().resolve()
    with wave.open(str(audio_path), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        sample_rate = wav.getframerate()
        frame_count = wav.getnframes()
        raw = wav.readframes(frame_count)
    duration = frame_count / float(sample_rate) if sample_rate else 0.0
    rms, normalized_rms = _pcm_rms(raw, sample_width)
    return AudioInspection(
        path=audio_path,
        duration_seconds=duration,
        sample_rate=sample_rate,
        channels=channels,
        sample_width=sample_width,
        frame_count=frame_count,
        rms=rms,
        normalized_rms=normalized_rms,
    )


def assert_audible_wav(
    path: str | Path,
    *,
    min_duration_seconds: float = 0.25,
    min_normalized_rms: float = 0.0005,
) -> AudioInspection:
    audio_path = Path(path).expanduser().resolve()
    if not audio_path.is_file():
        raise RuntimeError(f"audio file was not written: {audio_path}")
    if audio_path.stat().st_size <= 44:
        raise RuntimeError(f"audio file is empty or header-only: {audio_path}")
    try:
        inspection = inspect_wav(audio_path)
    except wave.Error as exc:
        raise RuntimeError(f"audio file is not a readable WAV: {audio_path}: {exc}") from exc
    if inspection.duration_seconds < min_duration_seconds:
        raise RuntimeError(
            f"audio duration {inspection.duration_seconds:.3f}s is below the minimum {min_duration_seconds:.3f}s"
        )
    if inspection.normalized_rms < min_normalized_rms:
        raise RuntimeError(
            f"audio appears silent: normalized RMS {inspection.normalized_rms:.6f} is below {min_normalized_rms:.6f}"
        )
    return inspection
