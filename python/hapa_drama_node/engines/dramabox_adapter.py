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


def resolve_dramabox_root(explicit_path: str | None = None) -> Path | None:
    candidates: list[Path] = []
    for raw in (explicit_path, os.environ.get("HAPA_DRAMA_DRAMABOX_ROOT")):
        if raw:
            candidates.append(Path(raw).expanduser())
    candidates.append(ROOT / "upstream" / "DramaBox")
    for candidate in candidates:
        path = candidate.resolve()
        if (path / "src" / "inference.py").is_file():
            return path
    return None


def resolve_dramabox_python(explicit_path: str | None = None, root: Path | None = None) -> Path | None:
    candidates: list[Path] = []
    for raw in (explicit_path, os.environ.get("HAPA_DRAMA_DRAMABOX_PYTHON")):
        if raw:
            candidates.append(Path(raw).expanduser())
    if root:
        candidates.append(root / ".venv" / "bin" / "python")
    candidates.append(Path(sys.executable))
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate if candidate.is_absolute() else candidate.absolute()
    return None


@lru_cache(maxsize=16)
def _probe_torch_cuda_cached(python_value: str | None) -> dict[str, Any]:
    if not python_value:
        return {"torch": False, "cuda": False, "reason": "python missing"}
    python_path = Path(python_value)
    probe = (
        "import json\n"
        "try:\n"
        " import torch\n"
        " print(json.dumps({'torch': True, 'cuda': bool(torch.cuda.is_available()), 'device_count': int(torch.cuda.device_count())}))\n"
        "except Exception as exc:\n"
        " print(json.dumps({'torch': False, 'cuda': False, 'reason': str(exc)}))\n"
    )
    try:
        completed = subprocess.run([str(python_path), "-c", probe], capture_output=True, text=True, timeout=15)
    except Exception as exc:
        return {"torch": False, "cuda": False, "reason": str(exc)}
    for line in completed.stdout.splitlines()[::-1]:
        try:
            payload = json.loads(line)
            if isinstance(payload, dict):
                return payload
        except json.JSONDecodeError:
            continue
    return {"torch": False, "cuda": False, "reason": _tail(completed.stderr) or "torch probe returned no JSON"}


def _probe_torch_cuda(python_path: Path | None) -> dict[str, Any]:
    return _probe_torch_cuda_cached(str(python_path) if python_path else None)


def _normalize_reference_audio(raw_path: str, output_path: Path) -> Path:
    source = Path(raw_path).expanduser().resolve()
    if not source.is_file():
        raise RuntimeError(f"voice reference clip does not exist: {source}")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return source
    ref_path = output_path.with_name("reference-dramabox.wav")
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
    assert_audible_wav(ref_path, min_duration_seconds=0.5, min_normalized_rms=0.0005)
    return ref_path


class DramaBoxEngine:
    name = "dramabox"

    def __init__(
        self,
        *,
        python_path: str | None = None,
        root_path: str | None = None,
        device: str | None = None,
        timeout_seconds: float = 600.0,
        cfg_scale: float = 2.5,
        stg_scale: float = 1.5,
        allow_cpu: bool = False,
    ) -> None:
        self.root = resolve_dramabox_root(root_path)
        self.python_path = resolve_dramabox_python(python_path, self.root)
        self.device = str(device or os.environ.get("HAPA_DRAMA_DRAMABOX_DEVICE") or "auto").strip() or "auto"
        self.timeout_seconds = float(timeout_seconds)
        self.cfg_scale = float(cfg_scale)
        self.stg_scale = float(stg_scale)
        self.allow_cpu = bool(allow_cpu)

    @staticmethod
    def is_available(python_path: str | None = None, root_path: str | None = None) -> bool:
        root = resolve_dramabox_root(root_path)
        python = resolve_dramabox_python(python_path, root)
        return bool(root and python and (root / "src" / "inference.py").is_file())

    @staticmethod
    def readiness(python_path: str | None = None, root_path: str | None = None, allow_cpu: bool = False) -> dict[str, Any]:
        root = resolve_dramabox_root(root_path)
        python = resolve_dramabox_python(python_path, root)
        configured = bool(root and python and (root / "src" / "inference.py").is_file())
        torch_status = _probe_torch_cuda(python) if python else {"torch": False, "cuda": False, "reason": "python missing"}
        practical = bool(configured and (torch_status.get("cuda") or allow_cpu))
        reason = None
        if not configured:
            reason = "DramaBox repo or Python environment is not configured"
        elif not torch_status.get("torch"):
            reason = f"DramaBox Python cannot import torch: {torch_status.get('reason') or 'unknown error'}"
        elif not torch_status.get("cuda") and not allow_cpu:
            reason = "DramaBox is wired but not practical on this machine without CUDA; set HAPA_DRAMA_DRAMABOX_ALLOW_CPU=1 to force an experimental CPU attempt"
        return {
            "configured": configured,
            "ready": practical,
            "root": str(root) if root else None,
            "python": str(python) if python else None,
            "torch": torch_status,
            "reason": reason,
        }

    def synthesize(self, *, text: str, output_path: Path, payload: dict[str, Any]) -> SynthesisResult:
        if not self.root or not self.python_path:
            raise RuntimeError("DramaBox is not configured. Run scripts/install_optional_engines.sh or set HAPA_DRAMA_DRAMABOX_ROOT and HAPA_DRAMA_DRAMABOX_PYTHON.")
        readiness = self.readiness(str(self.python_path), str(self.root), allow_cpu=self.allow_cpu)
        if not readiness.get("ready"):
            raise RuntimeError(str(readiness.get("reason") or "DramaBox is not ready"))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.exists():
            output_path.unlink()
        voice_clip_path = str(payload.get("voice_clip_path") or "").strip()
        ref_audio = _normalize_reference_audio(voice_clip_path, output_path) if voice_clip_path else None
        command = [
            str(self.python_path),
            str(self.root / "src" / "inference.py"),
            "--prompt",
            text,
            "--output",
            str(output_path),
            "--cfg-scale",
            str(payload.get("dramabox_cfg_scale") or self.cfg_scale),
            "--stg-scale",
            str(payload.get("dramabox_stg_scale") or self.stg_scale),
        ]
        if ref_audio:
            command.extend(["--voice-sample", str(ref_audio)])
        try:
            completed = subprocess.run(
                command,
                cwd=str(self.root),
                env={**os.environ.copy(), "PYTORCH_ENABLE_MPS_FALLBACK": "1"},
                check=True,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"DramaBox timed out after {self.timeout_seconds:.0f}s") from exc
        except subprocess.CalledProcessError as exc:
            detail = "\n".join(part for part in [_tail(exc.stdout), _tail(exc.stderr)] if part)
            raise RuntimeError(f"DramaBox failed: {detail}") from exc

        inspection = assert_audible_wav(output_path)
        return SynthesisResult(
            engine=self.name,
            audio_path=output_path,
            duration_seconds=inspection.duration_seconds,
            sample_rate=inspection.sample_rate,
            metadata={
                "model": "ResembleAI/Dramabox",
                "root_path": str(self.root),
                "python_path": str(self.python_path),
                "device": self.device,
                "voice_clip_path": voice_clip_path or None,
                "reference_audio_path": str(ref_audio) if ref_audio else None,
                "reference_audio_supplied": bool(ref_audio),
                "voice_clone_requested": bool(ref_audio),
                "voice_clone_supported": bool(ref_audio),
                "cfg_scale": float(payload.get("dramabox_cfg_scale") or self.cfg_scale),
                "stg_scale": float(payload.get("dramabox_stg_scale") or self.stg_scale),
                "stdout_tail": _tail(completed.stdout),
                "stderr_tail": _tail(completed.stderr),
            },
        )
