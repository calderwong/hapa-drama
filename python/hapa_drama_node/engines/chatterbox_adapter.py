from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..audio import assert_audible_wav
from .base import SynthesisResult


ROOT = Path(__file__).resolve().parents[3]


def _tail(text: str, max_chars: int = 1600) -> str:
    cleaned = (text or "").strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[-max_chars:]


def resolve_chatterbox_root(explicit_path: str | None = None) -> Path | None:
    candidates: list[Path] = []
    for raw in (explicit_path, os.environ.get("HAPA_DRAMA_CHATTERBOX_ROOT")):
        if raw:
            candidates.append(Path(raw).expanduser())
    candidates.extend(
        [
            ROOT / "upstream" / "chatterbox",
            Path.home() / "pinokio" / "api" / "Ultimate-TTS-Studio.git" / "app" / "chatterbox",
            Path.home() / "pinokio" / "api" / "Ultimate-TTS-Studio.git" / "app",
        ]
    )
    for candidate in candidates:
        path = candidate.resolve()
        if (path / "src" / "chatterbox").is_dir() or (path / "chatterbox" / "src" / "chatterbox").is_dir():
            return path
    return None


def _src_path(root: Path | None) -> Path | None:
    if not root:
        return None
    if (root / "src" / "chatterbox").is_dir():
        return root / "src"
    if (root / "chatterbox" / "src" / "chatterbox").is_dir():
        return root / "chatterbox" / "src"
    return None


def resolve_chatterbox_python(explicit_path: str | None = None, root: Path | None = None) -> Path | None:
    candidates: list[Path] = []
    for raw in (explicit_path, os.environ.get("HAPA_DRAMA_CHATTERBOX_PYTHON")):
        if raw:
            candidates.append(Path(raw).expanduser())
    if root:
        candidates.extend([root / ".venv" / "bin" / "python", root / "tts_env" / "bin" / "python"])
        if (root / "chatterbox").is_dir():
            candidates.extend(
                [
                    root / "chatterbox" / ".venv" / "bin" / "python",
                    root / "chatterbox" / "tts_env" / "bin" / "python",
                ]
            )
    candidates.append(Path(sys.executable))
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate if candidate.is_absolute() else candidate.absolute()
    return None


@lru_cache(maxsize=16)
def _python_can_find_chatterbox_cached(python_value: str, root_value: str | None) -> bool:
    python_path = Path(python_value)
    root = Path(root_value) if root_value else None
    env = os.environ.copy()
    src = _src_path(root)
    if src:
        env["PYTHONPATH"] = str(src) + os.pathsep + env.get("PYTHONPATH", "")
    try:
        completed = subprocess.run(
            [
                str(python_path),
                "-c",
                "import importlib.util; raise SystemExit(0 if importlib.util.find_spec('chatterbox') else 1)",
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return False
    return completed.returncode == 0


def _python_can_find_chatterbox(python_path: Path, root: Path | None) -> bool:
    return _python_can_find_chatterbox_cached(str(python_path), str(root) if root else None)


class ChatterboxEngine:
    name = "chatterbox"

    def __init__(
        self,
        *,
        python_path: str | None = None,
        root_path: str | None = None,
        device: str | None = None,
        model: str | None = None,
        timeout_seconds: float = 300.0,
        exaggeration: float = 0.55,
        cfg_weight: float = 0.5,
        temperature: float = 0.8,
    ) -> None:
        self.root = resolve_chatterbox_root(root_path)
        self.python_path = resolve_chatterbox_python(python_path, self.root)
        self.device = str(device or os.environ.get("HAPA_DRAMA_CHATTERBOX_DEVICE") or "auto").strip() or "auto"
        self.model = str(model or os.environ.get("HAPA_DRAMA_CHATTERBOX_MODEL") or "standard").strip() or "standard"
        self.timeout_seconds = float(timeout_seconds)
        self.exaggeration = float(exaggeration)
        self.cfg_weight = float(cfg_weight)
        self.temperature = float(temperature)

    @staticmethod
    def is_available(python_path: str | None = None, root_path: str | None = None) -> bool:
        root = resolve_chatterbox_root(root_path)
        python = resolve_chatterbox_python(python_path, root)
        return bool(python and _python_can_find_chatterbox(python, root))

    def _normalize_reference_audio(self, raw_path: str, output_path: Path) -> Path:
        source = Path(raw_path).expanduser().resolve()
        if not source.is_file():
            raise RuntimeError(f"voice reference clip does not exist: {source}")
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return source
        ref_path = output_path.with_name("reference-chatterbox.wav")
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(source),
                "-ac",
                "1",
                "-ar",
                "24000",
                "-t",
                "20",
                "-sample_fmt",
                "s16",
                str(ref_path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=45,
        )
        assert_audible_wav(ref_path, min_duration_seconds=5.0, min_normalized_rms=0.0005)
        return ref_path

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        env.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
        src = _src_path(self.root)
        if src:
            env["PYTHONPATH"] = str(src) + os.pathsep + env.get("PYTHONPATH", "")
        return env

    def synthesize(self, *, text: str, output_path: Path, payload: dict[str, Any]) -> SynthesisResult:
        if not self.python_path:
            raise RuntimeError("Chatterbox Python is not configured. Run scripts/install_optional_engines.sh or set HAPA_DRAMA_CHATTERBOX_PYTHON.")
        runner = ROOT / "scripts" / "engine_chatterbox_generate.py"
        if not runner.is_file():
            raise RuntimeError(f"Chatterbox runner is missing: {runner}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.exists():
            output_path.unlink()

        voice_clip_path = str(payload.get("voice_clip_path") or "").strip()
        ref_audio: Path | None = None
        if voice_clip_path:
            ref_audio = self._normalize_reference_audio(voice_clip_path, output_path)

        model = str(payload.get("chatterbox_model") or self.model).strip() or "standard"
        device = str(payload.get("chatterbox_device") or self.device).strip() or "auto"
        exaggeration = float(payload.get("chatterbox_exaggeration") or self.exaggeration)
        cfg_weight = float(payload.get("chatterbox_cfg_weight") or self.cfg_weight)
        temperature = float(payload.get("chatterbox_temperature") or self.temperature)
        command = [
            str(self.python_path),
            str(runner),
            "--text",
            text,
            "--output",
            str(output_path),
            "--device",
            device,
            "--model",
            model,
            "--exaggeration",
            str(exaggeration),
            "--cfg-weight",
            str(cfg_weight),
            "--temperature",
            str(temperature),
        ]
        if ref_audio:
            command.extend(["--voice-sample", str(ref_audio)])

        try:
            completed = subprocess.run(
                command,
                cwd=str(ROOT),
                env=self._env(),
                check=True,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"Chatterbox timed out after {self.timeout_seconds:.0f}s using model {model}") from exc
        except subprocess.CalledProcessError as exc:
            detail = "\n".join(part for part in [_tail(exc.stdout), _tail(exc.stderr)] if part)
            raise RuntimeError(f"Chatterbox failed using model {model}: {detail}") from exc

        inspection = assert_audible_wav(output_path)
        runner_metadata: dict[str, Any] = {}
        for line in completed.stdout.splitlines()[::-1]:
            try:
                value = json.loads(line)
                if isinstance(value, dict):
                    runner_metadata = value
                    break
            except json.JSONDecodeError:
                continue
        return SynthesisResult(
            engine=self.name,
            audio_path=output_path,
            duration_seconds=inspection.duration_seconds,
            sample_rate=inspection.sample_rate,
            metadata={
                "model": model,
                "repo_id": runner_metadata.get("repo_id") or ("ResembleAI/chatterbox-turbo" if "turbo" in model.lower() else "ResembleAI/chatterbox"),
                "device": runner_metadata.get("device") or device,
                "python_path": str(self.python_path),
                "root_path": str(self.root) if self.root else None,
                "voice_clip_path": voice_clip_path or None,
                "reference_audio_path": str(ref_audio) if ref_audio else None,
                "reference_audio_supplied": bool(ref_audio),
                "voice_clone_requested": bool(ref_audio),
                "voice_clone_supported": bool(ref_audio),
                "exaggeration": exaggeration,
                "cfg_weight": cfg_weight,
                "temperature": temperature,
                "stdout_tail": _tail(completed.stdout),
                "stderr_tail": _tail(completed.stderr),
            },
        )
