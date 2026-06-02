from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..audio import assert_audible_wav
from .base import SynthesisResult


PREFERRED_ENGLISH_VOICES = [
    "Samantha",
    "Daniel",
    "Karen",
    "Moira",
    "Tessa",
    "Eddy (English (US))",
    "Flo (English (US))",
    "Reed (English (US))",
    "Fred",
]


@lru_cache(maxsize=1)
def _available_voice_names() -> tuple[str, ...]:
    say_bin = shutil.which("say")
    if not say_bin:
        return ()
    try:
        result = subprocess.run(
            [say_bin, "-v", "?"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return ()
    names: list[str] = []
    voice_line = re.compile(r"^(.*?)\s+([a-z]{2}_[A-Z]{2})\s+#")
    for line in result.stdout.splitlines():
        match = voice_line.match(line.rstrip())
        if match:
            names.append(match.group(1).strip())
    return tuple(names)


def _voice_by_casefold(name: str, available: tuple[str, ...]) -> str | None:
    wanted = name.strip().casefold()
    if not wanted:
        return None
    for voice in available:
        if voice.casefold() == wanted:
            return voice
    return None


def _payload_sources(payload: dict[str, Any]) -> list[dict[str, Any]]:
    sources = [payload]
    profile = payload.get("voice_profile") if isinstance(payload.get("voice_profile"), dict) else {}
    if profile:
        sources.append(profile)
        for key in ("traits", "request_hints"):
            value = profile.get(key)
            if isinstance(value, dict):
                sources.append(value)
    return sources


def _requested_voice(payload: dict[str, Any], available: tuple[str, ...], default_voice: str | None) -> str:
    for source in _payload_sources(payload):
        for key in ("macos_voice", "system_voice", "say_voice", "voice_name"):
            value = str(source.get(key) or "").strip()
            if not value:
                continue
            matched = _voice_by_casefold(value, available)
            if matched:
                return matched
    if default_voice:
        matched = _voice_by_casefold(default_voice, available)
        if matched:
            return matched
    preferred = [voice for voice in PREFERRED_ENGLISH_VOICES if _voice_by_casefold(voice, available)]
    if not preferred:
        return available[0] if available else "Samantha"
    identity = str(payload.get("voice_profile_id") or payload.get("voice_id") or "").strip()
    if not identity:
        return preferred[0]
    digest = hashlib.sha256(identity.encode("utf-8")).digest()
    return preferred[int.from_bytes(digest[:2], "big") % len(preferred)]


def _speech_rate_wpm(text: str, payload: dict[str, Any], default_rate_wpm: int) -> int:
    timing = payload.get("timing") if isinstance(payload.get("timing"), dict) else {}
    target_duration = float(timing.get("target_duration_seconds") or 0)
    if target_duration > 0:
        word_count = max(1, len(re.findall(r"\w+", text)))
        return max(90, min(360, int(round((word_count / target_duration) * 60))))
    emotion = payload.get("emotion") if isinstance(payload.get("emotion"), dict) else {}
    intensity = float((emotion or {}).get("intensity") or 0)
    rate = int(default_rate_wpm)
    if intensity >= 0.7:
        rate -= 18
    elif intensity <= 0.15:
        rate += 8
    return max(90, min(360, rate))


class MacOSSpeechEngine:
    name = "macos-speech"

    def __init__(self, *, default_voice: str | None = None, default_rate_wpm: int = 178) -> None:
        self.default_voice = default_voice
        self.default_rate_wpm = default_rate_wpm

    @staticmethod
    def is_available() -> bool:
        return sys.platform == "darwin" and shutil.which("say") is not None and (
            shutil.which("afconvert") is not None or shutil.which("ffmpeg") is not None
        )

    def synthesize(self, *, text: str, output_path: Path, payload: dict[str, Any]) -> SynthesisResult:
        say_bin = shutil.which("say")
        afconvert_bin = shutil.which("afconvert")
        ffmpeg_bin = shutil.which("ffmpeg")
        if not say_bin or not (afconvert_bin or ffmpeg_bin):
            raise RuntimeError("macOS speech requires `say` and either `afconvert` or `ffmpeg`")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        temp_aiff = output_path.with_suffix(".aiff")
        if temp_aiff.exists():
            temp_aiff.unlink()
        if output_path.exists():
            output_path.unlink()

        available = _available_voice_names()
        voice = _requested_voice(payload, available, self.default_voice)
        rate_wpm = _speech_rate_wpm(text, payload, self.default_rate_wpm)
        say_cmd = [say_bin, "-v", voice, "-r", str(rate_wpm), "-o", str(temp_aiff)]
        timeout_seconds = max(30.0, min(240.0, len(text) / 12.0))
        try:
            subprocess.run(
                say_cmd,
                input=text,
                text=True,
                check=True,
                capture_output=True,
                timeout=timeout_seconds,
            )
            if afconvert_bin:
                subprocess.run(
                    [afconvert_bin, "-f", "WAVE", "-d", "LEI16@22050", str(temp_aiff), str(output_path)],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            else:
                subprocess.run(
                    [
                        ffmpeg_bin,
                        "-y",
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-i",
                        str(temp_aiff),
                        "-ac",
                        "1",
                        "-ar",
                        "22050",
                        "-sample_fmt",
                        "s16",
                        str(output_path),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
        finally:
            try:
                temp_aiff.unlink()
            except FileNotFoundError:
                pass

        inspection = assert_audible_wav(output_path)
        voice_clip_path = str(payload.get("voice_clip_path") or "").strip()
        return SynthesisResult(
            engine=self.name,
            audio_path=output_path,
            duration_seconds=inspection.duration_seconds,
            sample_rate=inspection.sample_rate,
            metadata={
                "macos_voice": voice,
                "rate_wpm": rate_wpm,
                "voice_clip_path": voice_clip_path or None,
                "voice_clone_supported": False,
                "reference_clip_mode": "profile_identity" if voice_clip_path else None,
            },
        )
