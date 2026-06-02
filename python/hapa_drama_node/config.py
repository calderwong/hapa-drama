from __future__ import annotations

import json
import os
import secrets
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def env_truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _resolve_path(raw: str, *, base: Path) -> Path:
    p = Path(str(raw)).expanduser()
    if not p.is_absolute():
        p = base / p
    return p.resolve()


def _default_voice_clip_path(cwd: Path) -> str | None:
    for candidate in (cwd / "data" / "default_voice" / "operator-default-reference.wav",):
        if candidate.is_file():
            return str(candidate.resolve())
    return None


def _load_or_create_token(token_file: Path, env_token: str | None) -> str:
    if env_token and env_token.strip():
        token = env_token.strip()
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(token + "\n", encoding="utf-8")
        try:
            token_file.chmod(0o600)
        except Exception:
            pass
        return token
    if token_file.exists():
        token = token_file.read_text(encoding="utf-8").strip()
        if token:
            return token
    token = secrets.token_hex(32)
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(token + "\n", encoding="utf-8")
    try:
        token_file.chmod(0o600)
    except Exception:
        pass
    return token


@dataclass(frozen=True)
class Settings:
    service_name: str
    api_version: str
    host: str
    port: int
    token: str
    token_file: Path
    storage_dir: Path
    artifacts_dir: Path
    db_path: Path
    event_log_path: Path
    runtime_file: Path
    default_route_file: Path
    stub_success: bool
    enable_macos_speech: bool
    macos_voice: str | None
    macos_rate_wpm: int
    min_audio_duration_seconds: float
    min_audio_normalized_rms: float
    default_mode: str
    default_tts_engine: str | None
    default_voice_profile_id: str | None
    default_voice_id: str | None
    default_voice_display_name: str | None
    default_voice_clip_path: str | None
    default_voice_ref_text: str | None
    enable_dramabox: bool
    dramabox_python: str | None
    dramabox_root: str | None
    dramabox_device: str | None
    dramabox_timeout_seconds: float
    dramabox_cfg_scale: float
    dramabox_stg_scale: float
    dramabox_allow_cpu: bool
    enable_mlx_dramabox: bool
    mlx_dramabox_cli: str | None
    mlx_dramabox_model: str | None
    mlx_dramabox_ref_text: str | None
    mlx_dramabox_timeout_seconds: float
    mlx_dramabox_cfg_scale: float
    mlx_dramabox_stg_scale: float
    mlx_dramabox_steps: int
    mlx_dramabox_gen_duration_seconds: float | None
    enable_chatterbox: bool
    chatterbox_python: str | None
    chatterbox_root: str | None
    chatterbox_device: str | None
    chatterbox_model: str | None
    chatterbox_timeout_seconds: float
    chatterbox_exaggeration: float
    chatterbox_cfg_weight: float
    chatterbox_temperature: float
    enable_mlx_audio: bool
    mlx_audio_cli: str | None
    mlx_audio_model: str | None
    mlx_audio_ref_text: str | None
    mlx_audio_timeout_seconds: float
    enable_piper: bool
    cards_service_url: str | None
    cymatica_service_url: str | None
    avatars_service_url: str | None
    phamiliars_service_url: str | None
    comms_service_url: str | None
    llm_service_url: str | None


def load_settings() -> Settings:
    cwd = Path.cwd().resolve()
    host = str(os.environ.get("HAPA_DRAMA_HOST") or "127.0.0.1").strip() or "127.0.0.1"
    port = int(os.environ.get("HAPA_DRAMA_PORT") or 8758)
    storage_dir = _resolve_path(os.environ.get("HAPA_DRAMA_STORAGE_DIR") or "./data", base=cwd)
    artifacts_dir = _resolve_path(os.environ.get("HAPA_DRAMA_ARTIFACTS_DIR") or str(storage_dir / "artifacts"), base=cwd)
    db_path = _resolve_path(os.environ.get("HAPA_DRAMA_DB_PATH") or str(storage_dir / "hapa_drama.sqlite3"), base=cwd)
    event_log_path = _resolve_path(os.environ.get("HAPA_DRAMA_EVENT_LOG") or str(storage_dir / "events.jsonl"), base=cwd)
    token_file = _resolve_path(os.environ.get("HAPA_DRAMA_TOKEN_FILE") or "./.node_token", base=cwd)
    runtime_file = _resolve_path(
        os.environ.get("HAPA_DRAMA_RUNTIME_FILE") or "./artifacts/runtime/hapa_drama_runtime.json",
        base=cwd,
    )
    default_route_file = _resolve_path(
        os.environ.get("HAPA_DRAMA_DEFAULT_ROUTE_FILE") or str(storage_dir / "default_route.json"),
        base=cwd,
    )
    storage_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    event_log_path.parent.mkdir(parents=True, exist_ok=True)
    default_route_file.parent.mkdir(parents=True, exist_ok=True)
    token = _load_or_create_token(token_file, os.environ.get("HAPA_DRAMA_TOKEN"))
    macos_default = "1" if sys.platform == "darwin" else "0"
    default_clip_path = _clean_url(os.environ.get("HAPA_DRAMA_DEFAULT_VOICE_CLIP_PATH")) or _default_voice_clip_path(cwd)
    return Settings(
        service_name="hapa-drama",
        api_version="v1",
        host=host,
        port=port,
        token=token,
        token_file=token_file,
        storage_dir=storage_dir,
        artifacts_dir=artifacts_dir,
        db_path=db_path,
        event_log_path=event_log_path,
        runtime_file=runtime_file,
        default_route_file=default_route_file,
        stub_success=env_truthy(os.environ.get("HAPA_DRAMA_STUB_SUCCESS") or "1"),
        enable_macos_speech=env_truthy(os.environ.get("HAPA_DRAMA_ENABLE_MACOS_SPEECH") or macos_default),
        macos_voice=_clean_url(os.environ.get("HAPA_DRAMA_MACOS_VOICE")),
        macos_rate_wpm=int(os.environ.get("HAPA_DRAMA_MACOS_RATE_WPM") or 178),
        min_audio_duration_seconds=float(os.environ.get("HAPA_DRAMA_MIN_AUDIO_SECONDS") or 0.25),
        min_audio_normalized_rms=float(os.environ.get("HAPA_DRAMA_MIN_AUDIO_RMS") or 0.003),
        default_mode=str(os.environ.get("HAPA_DRAMA_DEFAULT_MODE") or "drama").strip().lower() or "drama",
        default_tts_engine=_clean_url(os.environ.get("HAPA_DRAMA_DEFAULT_TTS_ENGINE") or "dramabox"),
        default_voice_profile_id=_clean_url(os.environ.get("HAPA_DRAMA_DEFAULT_VOICE_PROFILE_ID") or "profile-operator-default"),
        default_voice_id=_clean_url(os.environ.get("HAPA_DRAMA_DEFAULT_VOICE_ID") or "voice-operator-default"),
        default_voice_display_name=_clean_url(os.environ.get("HAPA_DRAMA_DEFAULT_VOICE_DISPLAY_NAME") or "Operator Default Voice"),
        default_voice_clip_path=default_clip_path,
        default_voice_ref_text=_clean_url(os.environ.get("HAPA_DRAMA_DEFAULT_VOICE_REF_TEXT")),
        enable_dramabox=env_truthy(os.environ.get("HAPA_DRAMA_ENABLE_DRAMABOX")),
        dramabox_python=_clean_url(os.environ.get("HAPA_DRAMA_DRAMABOX_PYTHON")),
        dramabox_root=_clean_url(os.environ.get("HAPA_DRAMA_DRAMABOX_ROOT")),
        dramabox_device=_clean_url(os.environ.get("HAPA_DRAMA_DRAMABOX_DEVICE")),
        dramabox_timeout_seconds=float(os.environ.get("HAPA_DRAMA_DRAMABOX_TIMEOUT_SECONDS") or 600),
        dramabox_cfg_scale=float(os.environ.get("HAPA_DRAMA_DRAMABOX_CFG_SCALE") or 2.5),
        dramabox_stg_scale=float(os.environ.get("HAPA_DRAMA_DRAMABOX_STG_SCALE") or 1.5),
        dramabox_allow_cpu=env_truthy(os.environ.get("HAPA_DRAMA_DRAMABOX_ALLOW_CPU")),
        enable_mlx_dramabox=env_truthy(os.environ.get("HAPA_DRAMA_ENABLE_MLX_DRAMABOX")),
        mlx_dramabox_cli=_clean_url(os.environ.get("HAPA_DRAMA_MLX_DRAMABOX_CLI")),
        mlx_dramabox_model=_clean_url(os.environ.get("HAPA_DRAMA_MLX_DRAMABOX_MODEL")),
        mlx_dramabox_ref_text=_clean_url(os.environ.get("HAPA_DRAMA_MLX_DRAMABOX_REF_TEXT")),
        mlx_dramabox_timeout_seconds=float(os.environ.get("HAPA_DRAMA_MLX_DRAMABOX_TIMEOUT_SECONDS") or 1200),
        mlx_dramabox_cfg_scale=float(os.environ.get("HAPA_DRAMA_MLX_DRAMABOX_CFG_SCALE") or 6.0),
        mlx_dramabox_stg_scale=float(os.environ.get("HAPA_DRAMA_MLX_DRAMABOX_STG_SCALE") or 1.5),
        mlx_dramabox_steps=int(os.environ.get("HAPA_DRAMA_MLX_DRAMABOX_STEPS") or 30),
        mlx_dramabox_gen_duration_seconds=(
            float(os.environ["HAPA_DRAMA_MLX_DRAMABOX_GEN_DURATION_SECONDS"])
            if os.environ.get("HAPA_DRAMA_MLX_DRAMABOX_GEN_DURATION_SECONDS")
            else None
        ),
        enable_chatterbox=env_truthy(os.environ.get("HAPA_DRAMA_ENABLE_CHATTERBOX")),
        chatterbox_python=_clean_url(os.environ.get("HAPA_DRAMA_CHATTERBOX_PYTHON")),
        chatterbox_root=_clean_url(os.environ.get("HAPA_DRAMA_CHATTERBOX_ROOT")),
        chatterbox_device=_clean_url(os.environ.get("HAPA_DRAMA_CHATTERBOX_DEVICE")),
        chatterbox_model=_clean_url(os.environ.get("HAPA_DRAMA_CHATTERBOX_MODEL")),
        chatterbox_timeout_seconds=float(os.environ.get("HAPA_DRAMA_CHATTERBOX_TIMEOUT_SECONDS") or 300),
        chatterbox_exaggeration=float(os.environ.get("HAPA_DRAMA_CHATTERBOX_EXAGGERATION") or 0.55),
        chatterbox_cfg_weight=float(os.environ.get("HAPA_DRAMA_CHATTERBOX_CFG_WEIGHT") or 0.5),
        chatterbox_temperature=float(os.environ.get("HAPA_DRAMA_CHATTERBOX_TEMPERATURE") or 0.8),
        enable_mlx_audio=env_truthy(os.environ.get("HAPA_DRAMA_ENABLE_MLX_AUDIO")),
        mlx_audio_cli=_clean_url(os.environ.get("HAPA_DRAMA_MLX_AUDIO_CLI")),
        mlx_audio_model=_clean_url(os.environ.get("HAPA_DRAMA_MLX_AUDIO_MODEL")),
        mlx_audio_ref_text=_clean_url(os.environ.get("HAPA_DRAMA_MLX_AUDIO_REF_TEXT")),
        mlx_audio_timeout_seconds=float(os.environ.get("HAPA_DRAMA_MLX_AUDIO_TIMEOUT_SECONDS") or 180),
        enable_piper=env_truthy(os.environ.get("HAPA_DRAMA_ENABLE_PIPER")),
        cards_service_url=_clean_url(os.environ.get("HAPA_DRAMA_CARDS_SERVICE_URL")),
        cymatica_service_url=_clean_url(os.environ.get("HAPA_DRAMA_CYMATICA_SERVICE_URL")),
        avatars_service_url=_clean_url(os.environ.get("HAPA_DRAMA_AVATAR_SERVICE_URL")),
        phamiliars_service_url=_clean_url(os.environ.get("HAPA_DRAMA_PHAMILIAR_SERVICE_URL")),
        comms_service_url=_clean_url(os.environ.get("HAPA_DRAMA_COMMS_SERVICE_URL")),
        llm_service_url=_clean_url(os.environ.get("HAPA_DRAMA_LLM_SERVICE_URL")),
    )


def _clean_url(raw: str | None) -> str | None:
    value = str(raw or "").strip()
    return value or None


def write_runtime_file(settings: Settings) -> None:
    payload = {
        "service": settings.service_name,
        "node": ".hapaDrama",
        "api_version": settings.api_version,
        "base_url": f"http://{settings.host}:{settings.port}",
        "token_path": str(settings.token_file),
        "storage_dir": str(settings.storage_dir),
        "artifacts_dir": str(settings.artifacts_dir),
        "db_path": str(settings.db_path),
        "event_log_path": str(settings.event_log_path),
        "default_route_file": str(settings.default_route_file),
        "default_route": {
            "mode": settings.default_mode,
            "tts_engine": settings.default_tts_engine,
            "voice_profile_id": settings.default_voice_profile_id,
            "voice_id": settings.default_voice_id,
            "voice_display_name": settings.default_voice_display_name,
            "voice_clip_path": settings.default_voice_clip_path,
            "reference_text": settings.default_voice_ref_text,
            "reference_text_is_transcript": False,
        },
        "engines": {
            "dramabox": {
                "enabled": settings.enable_dramabox,
                "root": settings.dramabox_root,
                "python": settings.dramabox_python,
                "device": settings.dramabox_device,
                "timeout_seconds": settings.dramabox_timeout_seconds,
            },
            "dramabox_mlx": {
                "enabled": settings.enable_mlx_dramabox,
                "cli_path": settings.mlx_dramabox_cli,
                "model": settings.mlx_dramabox_model,
                "timeout_seconds": settings.mlx_dramabox_timeout_seconds,
                "cfg_scale": settings.mlx_dramabox_cfg_scale,
                "stg_scale": settings.mlx_dramabox_stg_scale,
                "steps": settings.mlx_dramabox_steps,
                "gen_duration_seconds": settings.mlx_dramabox_gen_duration_seconds,
            },
            "chatterbox": {
                "enabled": settings.enable_chatterbox,
                "root": settings.chatterbox_root,
                "python": settings.chatterbox_python,
                "device": settings.chatterbox_device,
                "model": settings.chatterbox_model,
                "timeout_seconds": settings.chatterbox_timeout_seconds,
            },
            "mlx_audio": {
                "enabled": settings.enable_mlx_audio,
                "cli_path": settings.mlx_audio_cli,
                "model": settings.mlx_audio_model,
                "timeout_seconds": settings.mlx_audio_timeout_seconds,
            },
            "piper": {"enabled": settings.enable_piper},
            "macos_speech": {
                "enabled": settings.enable_macos_speech,
                "default_voice": settings.macos_voice,
                "rate_wpm": settings.macos_rate_wpm,
            },
            "stub": {"enabled": settings.stub_success},
        },
        "peers": {
            "cards": settings.cards_service_url,
            "cymatica": settings.cymatica_service_url,
            "avatars": settings.avatars_service_url,
            "phamiliars": settings.phamiliars_service_url,
            "comms": settings.comms_service_url,
            "llm": settings.llm_service_url,
        },
        "time": utc_now_iso(),
    }
    settings.runtime_file.parent.mkdir(parents=True, exist_ok=True)
    settings.runtime_file.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
