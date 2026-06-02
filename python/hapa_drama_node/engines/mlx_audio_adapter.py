from __future__ import annotations

import os
import shutil
import subprocess
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


def _known_pinokio_cli_paths() -> list[Path]:
    home = Path.home()
    roots = [
        home / "pinokio" / "drive" / "drives" / "pip" / "mlx-audio",
    ]
    candidates: list[Path] = []
    for root in roots:
        if root.is_dir():
            direct = root / "bin" / "mlx_audio.tts.generate"
            if direct.is_file():
                candidates.append(direct)
            candidates.extend(sorted(root.glob("*/bin/mlx_audio.tts.generate"), reverse=True))
    candidates.append(home / "pinokio" / "drive" / "drives" / "pip" / "mlx-audio" / "0.2.6" / "bin" / "mlx_audio.tts.generate")
    return candidates


def resolve_mlx_audio_cli(explicit_path: str | None = None) -> Path | None:
    if explicit_path:
        path = Path(explicit_path).expanduser()
        if path.is_file():
            return path.resolve()
    path_from_env = os.environ.get("HAPA_DRAMA_MLX_AUDIO_CLI")
    if path_from_env:
        path = Path(path_from_env).expanduser()
        if path.is_file():
            return path.resolve()
    path_from_shell = shutil.which("mlx_audio.tts.generate")
    if path_from_shell:
        return Path(path_from_shell).resolve()
    for candidate in _known_pinokio_cli_paths():
        if candidate.is_file():
            return candidate.resolve()
    return None


def resolve_dramabox_mlx_cli(explicit_path: str | None = None) -> Path | None:
    if explicit_path:
        path = Path(explicit_path).expanduser()
        if path.is_file():
            return path.resolve()
    path_from_env = os.environ.get("HAPA_DRAMA_MLX_DRAMABOX_CLI")
    if path_from_env:
        path = Path(path_from_env).expanduser()
        if path.is_file():
            return path.resolve()
    repo_cli = ROOT / "upstream" / "mlx-audio" / ".venv" / "bin" / "mlx_audio.tts.generate"
    if repo_cli.is_file():
        return repo_cli.resolve()
    return None


def _payload_ref_text(payload: dict[str, Any], default_ref_text: str | None) -> str | None:
    for source in (payload, payload.get("request") if isinstance(payload.get("request"), dict) else {}):
        if not isinstance(source, dict):
            continue
        for key in ("ref_text", "reference_text", "voice_clip_text"):
            value = str(source.get(key) or "").strip()
            if value:
                return value
    profile = payload.get("voice_profile") if isinstance(payload.get("voice_profile"), dict) else {}
    hints = profile.get("request_hints") if isinstance(profile.get("request_hints"), dict) else {}
    transcript_marked = any(
        str(source.get(key) or "").strip().lower() in {"1", "true", "yes", "on"}
        for source in (profile, hints)
        for key in ("reference_text_is_transcript", "ref_text_is_transcript", "voice_clip_text_is_transcript")
    ) or any(
        str(source.get(key) or "").strip().lower() in {"transcript", "caption", "manual_transcript", "manual-caption"}
        for source in (profile, hints)
        for key in ("reference_text_source", "ref_text_source")
    )
    if transcript_marked:
        for source in (profile, hints):
            for key in ("ref_text", "reference_text", "voice_clip_text"):
                value = str(source.get(key) or "").strip()
                if value:
                    return value
    value = str(default_ref_text or "").strip()
    return value or None


def _model_likely_clone_capable(model: str) -> bool:
    lowered = model.casefold()
    return any(marker in lowered for marker in ("dramabox", "spark", "indextts", "dia", "outetts", "sesame", "csm", "llama"))


def _plain_script_to_dramabox_prompt(text: str, payload: dict[str, Any]) -> str:
    prompt = str(payload.get("dramabox_prompt") or payload.get("scene_prompt") or "").strip()
    if prompt:
        return prompt
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return text
    if '"' in cleaned or "“" in cleaned or "”" in cleaned:
        return cleaned
    speaker = str(payload.get("dramabox_speaker") or "A clear male narrator").strip() or "A clear male narrator"
    style = str(payload.get("dramabox_style") or "speaks calmly in a natural conversational voice").strip()
    dialogue = cleaned.replace('"', "'")
    if style:
        return f'{speaker} {style}, "{dialogue}"'
    return f'{speaker} says, "{dialogue}"'


class MLXAudioEngine:
    name = "mlx-audio"

    def __init__(
        self,
        *,
        cli_path: str | None = None,
        model: str | None = None,
        ref_text: str | None = None,
        timeout_seconds: float = 180.0,
        engine_name: str | None = None,
        cfg_scale: float | None = None,
        stg_scale: float | None = None,
        steps: int | None = None,
        gen_duration_seconds: float | None = None,
        duration_multiplier: float | None = None,
        text_encoder_model: str | None = None,
        allow_auto_cli: bool = True,
    ) -> None:
        if engine_name:
            self.name = engine_name
        self.cli_path = resolve_mlx_audio_cli(cli_path) if allow_auto_cli or cli_path else None
        self.model = str(model or os.environ.get("HAPA_DRAMA_MLX_AUDIO_MODEL") or "mlx-community/IndexTTS").strip()
        self.ref_text = ref_text or os.environ.get("HAPA_DRAMA_MLX_AUDIO_REF_TEXT")
        self.timeout_seconds = float(timeout_seconds)
        self.cfg_scale = cfg_scale
        self.stg_scale = stg_scale
        self.steps = steps
        self.gen_duration_seconds = gen_duration_seconds
        self.duration_multiplier = duration_multiplier
        self.text_encoder_model = text_encoder_model

    @staticmethod
    def is_available(cli_path: str | None = None) -> bool:
        return resolve_mlx_audio_cli(cli_path) is not None

    def _normalize_reference_audio(self, raw_path: str, output_path: Path) -> Path:
        source = Path(raw_path).expanduser().resolve()
        if not source.is_file():
            raise RuntimeError(f"voice reference clip does not exist: {source}")
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return source
        ref_path = output_path.with_name("reference-voice.wav")
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

    def _prepare_text(self, text: str, payload: dict[str, Any]) -> str:
        return text

    def synthesize(self, *, text: str, output_path: Path, payload: dict[str, Any]) -> SynthesisResult:
        if not self.cli_path:
            raise RuntimeError("MLX-Audio CLI is not configured. Set HAPA_DRAMA_MLX_AUDIO_CLI or install mlx_audio.tts.generate.")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.exists():
            output_path.unlink()

        prefix = output_path.with_suffix("")
        prepared_text = self._prepare_text(text, payload)
        command = [
            str(self.cli_path),
            "--model",
            self.model,
            "--text",
            prepared_text,
            "--file_prefix",
            str(prefix),
            "--audio_format",
            "wav",
            "--join_audio",
        ]
        voice_clip_path = str(payload.get("voice_clip_path") or "").strip()
        ref_audio: Path | None = None
        ref_text: str | None = None
        if voice_clip_path:
            ref_audio = self._normalize_reference_audio(voice_clip_path, output_path)
            command.extend(["--ref_audio", str(ref_audio)])
            ref_text = _payload_ref_text(payload, self.ref_text)
            if ref_text:
                command.extend(["--ref_text", ref_text])
        voice = str(payload.get("mlx_voice") or payload.get("voice_name") or "").strip()
        if voice:
            command.extend(["--voice", voice])
        cfg_scale = payload.get("mlx_audio_cfg_scale")
        if cfg_scale is None:
            cfg_scale = payload.get("dramabox_cfg_scale")
        if cfg_scale is None:
            cfg_scale = self.cfg_scale
        if cfg_scale is not None:
            command.extend(["--cfg_scale", str(cfg_scale)])
        stg_scale = payload.get("mlx_audio_stg_scale")
        if stg_scale is None:
            stg_scale = payload.get("dramabox_stg_scale")
        if stg_scale is None:
            stg_scale = self.stg_scale
        if stg_scale is not None:
            command.extend(["--stg_scale", str(stg_scale)])
        stg_block = payload.get("mlx_audio_stg_block")
        if stg_block is None:
            stg_block = payload.get("dramabox_stg_block")
        if stg_block is not None:
            command.extend(["--stg_block", str(stg_block)])
        rescale_scale = payload.get("mlx_audio_rescale_scale")
        if rescale_scale is None:
            rescale_scale = payload.get("dramabox_rescale_scale")
        if rescale_scale is not None:
            command.extend(["--rescale_scale", str(rescale_scale)])
        steps = payload.get("mlx_audio_steps")
        if steps is None:
            steps = payload.get("dramabox_steps")
        if steps is None:
            steps = self.steps
        if steps is not None:
            command.extend(["--steps", str(steps)])
        gen_duration = payload.get("mlx_audio_gen_duration_seconds")
        if gen_duration is None:
            gen_duration = payload.get("dramabox_gen_duration_seconds")
        if gen_duration is None:
            timing = payload.get("timing") if isinstance(payload.get("timing"), dict) else {}
            gen_duration = timing.get("target_duration_seconds")
        if gen_duration is None:
            gen_duration = self.gen_duration_seconds
        if gen_duration:
            command.extend(["--gen_duration", str(gen_duration)])
        duration_multiplier = payload.get("mlx_audio_duration_multiplier")
        if duration_multiplier is None:
            duration_multiplier = payload.get("dramabox_duration_multiplier")
        if duration_multiplier is None:
            duration_multiplier = self.duration_multiplier
        if duration_multiplier is not None:
            command.extend(["--duration_multiplier", str(duration_multiplier)])
        seed = payload.get("mlx_audio_seed")
        if seed is None:
            seed = payload.get("dramabox_seed")
        if seed is not None:
            command.extend(["--seed", str(seed)])
        text_encoder_model = str(payload.get("mlx_audio_text_encoder_model") or payload.get("dramabox_text_encoder_model") or self.text_encoder_model or "").strip()
        if text_encoder_model:
            command.extend(["--text_encoder_model", text_encoder_model])

        env = os.environ.copy()
        env.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
        try:
            completed = subprocess.run(
                command,
                cwd=str(output_path.parent),
                env=env,
                check=True,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"MLX-Audio timed out after {self.timeout_seconds:.0f}s using model {self.model}") from exc
        except subprocess.CalledProcessError as exc:
            detail = "\n".join(part for part in [_tail(exc.stdout), _tail(exc.stderr)] if part)
            raise RuntimeError(f"MLX-Audio failed using model {self.model}: {detail}") from exc

        generated_path = output_path if output_path.is_file() else prefix.with_suffix(".wav")
        if not generated_path.is_file():
            candidates = sorted(output_path.parent.glob(prefix.name + "*.wav"), key=lambda p: p.stat().st_mtime, reverse=True)
            if not candidates:
                detail = "\n".join(part for part in [_tail(completed.stdout), _tail(completed.stderr)] if part)
                raise RuntimeError(f"MLX-Audio completed but did not write a WAV for prefix {prefix}: {detail}")
            generated_path = candidates[0]
        if generated_path.resolve() != output_path.resolve():
            shutil.copyfile(generated_path, output_path)

        inspection = assert_audible_wav(output_path)
        return SynthesisResult(
            engine=self.name,
            audio_path=output_path,
            duration_seconds=inspection.duration_seconds,
            sample_rate=inspection.sample_rate,
            metadata={
                "model": self.model,
                "cli_path": str(self.cli_path),
                "voice_clip_path": voice_clip_path or None,
                "reference_audio_path": str(ref_audio) if ref_audio else None,
                "reference_audio_supplied": bool(ref_audio),
                "reference_text_supplied": bool(ref_text),
                "reference_text": ref_text,
                "voice_clone_requested": bool(ref_audio),
                "voice_clone_supported": bool(ref_audio and _model_likely_clone_capable(self.model)),
                "cfg_scale": float(cfg_scale) if cfg_scale is not None else None,
                "stg_scale": float(stg_scale) if stg_scale is not None else None,
                "stg_block": int(stg_block) if stg_block is not None else None,
                "rescale_scale": str(rescale_scale) if rescale_scale is not None else None,
                "steps": int(steps) if steps is not None else None,
                "gen_duration_seconds": float(gen_duration) if gen_duration else None,
                "duration_multiplier": float(duration_multiplier) if duration_multiplier is not None else None,
                "text_encoder_model": text_encoder_model or None,
                "prompt_text": prepared_text if prepared_text != text else None,
                "stdout_tail": _tail(completed.stdout),
                "stderr_tail": _tail(completed.stderr),
            },
        )


class DramaBoxMLXEngine(MLXAudioEngine):
    name = "dramabox-mlx"

    def __init__(
        self,
        *,
        cli_path: str | None = None,
        model: str | None = None,
        ref_text: str | None = None,
        timeout_seconds: float = 1200.0,
        cfg_scale: float = 6.0,
        stg_scale: float = 1.5,
        steps: int = 30,
        gen_duration_seconds: float | None = None,
    ) -> None:
        super().__init__(
            cli_path=str(resolve_dramabox_mlx_cli(cli_path) or ""),
            model=model or os.environ.get("HAPA_DRAMA_MLX_DRAMABOX_MODEL") or "mlx-community/ResembleAI-Dramabox",
            ref_text=ref_text or os.environ.get("HAPA_DRAMA_MLX_DRAMABOX_REF_TEXT"),
            timeout_seconds=timeout_seconds,
            engine_name=self.name,
            cfg_scale=cfg_scale,
            stg_scale=stg_scale,
            steps=steps,
            gen_duration_seconds=gen_duration_seconds,
            allow_auto_cli=False,
        )

    @staticmethod
    def is_available(cli_path: str | None = None) -> bool:
        return resolve_dramabox_mlx_cli(cli_path) is not None

    def _normalize_reference_audio(self, raw_path: str, output_path: Path) -> Path:
        source = Path(raw_path).expanduser().resolve()
        if not source.is_file():
            raise RuntimeError(f"voice reference clip does not exist: {source}")
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return source
        ref_path = output_path.with_name("reference-dramabox-mlx.wav")
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(source),
                "-af",
                "silenceremove=start_periods=1:start_duration=0.15:start_threshold=-35dB,loudnorm=I=-18:TP=-2:LRA=7",
                "-t",
                "8",
                "-ac",
                "2",
                "-ar",
                "48000",
                "-sample_fmt",
                "s16",
                str(ref_path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=45,
        )
        assert_audible_wav(ref_path, min_duration_seconds=2.0, min_normalized_rms=0.0005)
        return ref_path

    def _prepare_text(self, text: str, payload: dict[str, Any]) -> str:
        return _plain_script_to_dramabox_prompt(text, payload)
