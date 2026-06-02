from __future__ import annotations

import ipaddress
import json
import os
import sys
import base64
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .auth import verify_request_token
from .config import Settings, load_settings, utc_now_iso, write_runtime_file
from .engines.chatterbox_adapter import ChatterboxEngine
from .engines.dramabox_adapter import DramaBoxEngine
from .engines.macos_speech_adapter import MacOSSpeechEngine
from .engines.mlx_audio_adapter import DramaBoxMLXEngine, MLXAudioEngine
from .flow_voiceovers import (
    build_flow_voiceover_manifest,
    flow_voiceover_audio_path,
    flow_voiceover_queue_counts,
    process_flow_voiceover_queue,
    read_flow_voiceover_manifest,
    safe_flow_id,
    with_public_urls,
)
from .persistence import DramaStore
from .provenance import file_sha256
from .router import DramaRouter


class CommandRequest(BaseModel):
    api_version: str = "v1"
    command_id: str = Field(min_length=1)
    actor: str = "anonymous"
    kind: str = Field(min_length=1)
    mode: str = "auto"
    payload: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)
    options: dict[str, Any] = Field(default_factory=dict)


class VoiceProfileUploadRequest(BaseModel):
    profile_id: Optional[str] = None
    voice_id: Optional[str] = None
    display_name: str = "Voice Clip Profile"
    description: Optional[str] = None
    default_mode: str = "auto"
    filename: str = "voice.wav"
    clip_base64: str = Field(min_length=1)
    traits: dict[str, Any] = Field(default_factory=dict)
    request_hints: dict[str, Any] = Field(default_factory=dict)


class DefaultRouteRequest(BaseModel):
    mode: Optional[str] = None
    tts_engine: Optional[str] = None
    voice_profile_id: Optional[str] = None
    voice_id: Optional[str] = None
    voice_display_name: Optional[str] = None
    voice_clip_path: Optional[str] = None
    reference_text: Optional[str] = None
    reference_text_is_transcript: Optional[bool] = None


class FlowVoiceoverQueueRequest(BaseModel):
    flow: dict[str, Any] = Field(default_factory=dict)
    flow_id: Optional[str] = None
    id: Optional[str] = None
    flow_name: Optional[str] = None
    name: Optional[str] = None
    summary: Optional[str] = None
    steps: list[dict[str, Any]] = Field(default_factory=list)
    mode: Optional[str] = "drama"
    tts_engine: Optional[str] = "dramabox"
    voice_profile_id: Optional[str] = None
    voice_id: Optional[str] = None
    voice_clip_path: Optional[str] = None
    use_default_voice: bool = True
    dramabox_cfg_scale: Optional[float] = None
    dramabox_stg_scale: Optional[float] = None
    dramabox_stg_block: Optional[int] = None
    dramabox_rescale_scale: Optional[float | str] = None
    dramabox_steps: Optional[int] = None
    dramabox_duration_multiplier: Optional[float] = None
    dramabox_seed: Optional[int] = None
    process: bool = True
    force: bool = False
    provenance: dict[str, Any] = Field(default_factory=dict)


class FlowVoiceoverProcessRequest(BaseModel):
    force: bool = False


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _looks_like_reference_note(value: str | None) -> bool:
    lowered = str(value or "").strip().lower()
    if not lowered:
        return False
    return any(
        marker in lowered
        for marker in (
            "browser microphone voice sample",
            "voice sample recorded",
            "operator reference voice clip",
            "reference voice clip",
            "desktop reference clip",
            "reference clip from",
        )
    )


def _marked_reference_transcript(source: dict[str, Any]) -> bool:
    hints = source.get("request_hints") if isinstance(source.get("request_hints"), dict) else {}
    for item in (source, hints):
        if any(_truthy(item.get(key)) for key in ("reference_text_is_transcript", "ref_text_is_transcript", "voice_clip_text_is_transcript")):
            return True
        source_value = str(item.get("reference_text_source") or item.get("ref_text_source") or "").strip().lower()
        if source_value in {"transcript", "caption", "manual_transcript", "manual-caption"}:
            return True
    return False


def _settings_default_route_payload(settings: Settings) -> dict[str, Any]:
    return {
        "mode": settings.default_mode,
        "tts_engine": settings.default_tts_engine,
        "voice_profile_id": settings.default_voice_profile_id,
        "voice_id": settings.default_voice_id,
        "voice_display_name": settings.default_voice_display_name,
        "voice_clip_path": settings.default_voice_clip_path,
        "reference_text": settings.default_voice_ref_text,
        "reference_text_is_transcript": False,
    }


def _normalize_default_route(settings: Settings, store: DramaStore, route: dict[str, Any] | None = None) -> dict[str, Any]:
    provided = route or {}
    base = _settings_default_route_payload(settings)
    for key, value in provided.items():
        if key in base and value is not None:
            if key == "reference_text_is_transcript":
                base[key] = _truthy(value)
            else:
                base[key] = str(value).strip() or None
    mode = str(base.get("mode") or "drama").strip().lower()
    base["mode"] = mode if mode in {"auto", "drama", "flow", "ultrafast"} else "drama"
    engine = str(base.get("tts_engine") or "dramabox").strip().lower().replace("_", "-")
    base["tts_engine"] = engine or "dramabox"
    profile_id = str(base.get("voice_profile_id") or "").strip()
    if profile_id:
        profile = store.get_voice_profile(profile_id)
        if profile:
            base["voice_profile_id"] = profile_id
            if "voice_id" not in provided:
                base["voice_id"] = profile.get("voice_id")
            if "voice_display_name" not in provided:
                base["voice_display_name"] = profile.get("display_name")
            if "voice_clip_path" not in provided:
                base["voice_clip_path"] = profile.get("clip_audio_path")
            hints = profile.get("request_hints") if isinstance(profile.get("request_hints"), dict) else {}
            if "reference_text" not in provided and _marked_reference_transcript(profile):
                base["reference_text"] = hints.get("reference_text") or hints.get("ref_text") or base.get("reference_text")
                base["reference_text_is_transcript"] = True
    if not _truthy(base.get("reference_text_is_transcript")) or _looks_like_reference_note(base.get("reference_text")):
        base["reference_text"] = None
        base["reference_text_is_transcript"] = False
    return base


def _load_default_route(settings: Settings, store: DramaStore) -> dict[str, Any]:
    if not settings.default_route_file.is_file():
        return _normalize_default_route(settings, store)
    try:
        payload = json.loads(settings.default_route_file.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    return _normalize_default_route(settings, store, payload if isinstance(payload, dict) else {})


def _save_default_route(settings: Settings, route: dict[str, Any]) -> None:
    settings.default_route_file.parent.mkdir(parents=True, exist_ok=True)
    settings.default_route_file.write_text(json.dumps(route, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _current_default_route(request: Request) -> dict[str, Any]:
    route = getattr(request.app.state, "default_route", None)
    if isinstance(route, dict) and route:
        return route
    return _normalize_default_route(request.app.state.settings, request.app.state.store)


def _ensure_default_voice_profile(settings: Settings, store: DramaStore) -> None:
    if not settings.default_voice_profile_id or not settings.default_voice_id or not settings.default_voice_clip_path:
        return
    clip_path = Path(settings.default_voice_clip_path).expanduser().resolve()
    if not clip_path.is_file():
        return
    store.create_voice(
        settings.default_voice_id,
        settings.default_voice_display_name or "Default Voice",
        {
            "role": "default_profile",
            "source": "desktop_reference_clip",
            "tts_engine": settings.default_tts_engine,
        },
    )
    store.create_voice_profile(
        {
            "profile_id": settings.default_voice_profile_id,
            "voice_id": settings.default_voice_id,
            "display_name": settings.default_voice_display_name or "Default Voice",
            "description": "Default Hapa Drama profile bound to an operator-provided reference clip.",
            "default_mode": settings.default_mode if settings.default_mode in {"auto", "drama", "flow", "ultrafast"} else "drama",
            "clip_audio_path": str(clip_path),
            "clip_audio_sha256": file_sha256(clip_path),
            "traits": {
                "default_route": True,
                "source": "operator_default_reference",
                "engine": settings.default_tts_engine,
            },
            "request_hints": {
                "tts_engine": settings.default_tts_engine,
                "preferred_engine": settings.default_tts_engine,
            },
            "created_by": "hapa-drama-defaults",
        }
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    store = DramaStore(settings)
    _ensure_default_voice_profile(settings, store)
    default_route = _load_default_route(settings, store)
    router = DramaRouter(settings, store)
    router.set_default_route(default_route)
    app.state.settings = settings
    app.state.store = store
    app.state.router = router
    app.state.default_route = default_route
    app.state.allow_query_token = os.environ.get("HAPA_DRAMA_ALLOW_QUERY_TOKEN") or "0"
    write_runtime_file(settings)
    try:
        yield
    finally:
        store.close()


app = FastAPI(title="Hapa Drama", lifespan=lifespan)
_WEB_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "web"))
_ROOT_DIR = Path(__file__).resolve().parents[2]
_NODE_ID = ".hapaDrama"
if os.path.isdir(_WEB_DIR):
    app.mount("/web", StaticFiles(directory=_WEB_DIR), name="web")


def _require_auth(request: Request) -> None:
    settings: Settings = request.app.state.settings
    verify_request_token(request, settings.token)


def _peers_payload(settings: Settings) -> dict[str, Any]:
    peers = {
        "cards": settings.cards_service_url,
        "cymatica": settings.cymatica_service_url,
        "avatars": settings.avatars_service_url,
        "phamiliars": settings.phamiliars_service_url,
        "comms": settings.comms_service_url,
        "llm": settings.llm_service_url,
    }
    return {"peers": peers, "connected": {k: bool(v) for k, v in peers.items()}}


def _generation_or_404(request: Request, generation_id: str) -> dict[str, Any]:
    generation = request.app.state.store.get_generation(generation_id)
    if not generation:
        raise HTTPException(status_code=404, detail="generation not found")
    return generation


def _generation_assets(generation: dict[str, Any]) -> list[dict[str, Any]]:
    generation_id = str(generation.get("generation_id") or "")
    assets: list[dict[str, Any]] = []
    if generation.get("audio_path"):
        assets.append(
            {
                "kind": "audio",
                "label": "Audio WAV",
                "path": f"/v1/generations/{generation_id}/audio",
                "ready": True,
                "duration_seconds": generation.get("duration_seconds"),
                "sample_rate": generation.get("sample_rate"),
            }
        )
    if generation.get("card_id"):
        assets.append({"kind": "card", "label": "Card JSON", "path": f"/v1/generations/{generation_id}/card", "ready": True})
    if generation.get("cymatica_bundle_path"):
        assets.append({"kind": "cymatica_manifest", "label": "Cymatica Manifest", "path": f"/v1/generations/{generation_id}/cymatica-manifest", "ready": True})
    if generation.get("cymatica_handoff_zip_path"):
        assets.append({"kind": "cymatica_handoff_zip", "label": "Cymatica Handoff Zip", "path": f"/v1/generations/{generation_id}/cymatica-handoff", "ready": True})
    return assets


def _generation_progress(generation: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    progress_by_kind = {
        "command.accepted": 0.08,
        "engine.selected": 0.18,
        "generation.started": 0.32,
        "asset.written": 0.58,
        "asset.validated": 0.66,
        "card.minted": 0.76,
        "cymatica.bundle.written": 0.88,
        "generation.completed": 1.0,
        "generation.failed": 1.0,
        "command.failed": 1.0,
    }
    stage_by_kind = {
        "command.accepted": "accepted",
        "engine.selected": "engine selected",
        "generation.started": "synthesizing",
        "asset.written": "audio written",
        "asset.validated": "audio validated",
        "card.minted": "card minted",
        "cymatica.bundle.written": "cymatica handoff ready",
        "generation.completed": "completed",
        "generation.failed": "failed",
        "command.failed": "failed",
    }
    progress = 0.0
    stage = "queued"
    for event in events:
        kind = str(event.get("kind") or "")
        if kind in progress_by_kind:
            progress = max(progress, progress_by_kind[kind])
            stage = stage_by_kind[kind]
    status = str(generation.get("status") or "unknown")
    if status == "succeeded":
        progress = 1.0
        stage = "completed"
    elif status == "failed":
        progress = 1.0
        stage = "failed"
    elif status == "running" and progress < 0.32:
        progress = 0.32
        stage = "synthesizing"
    return {"status": status, "stage": stage, "progress": progress}


def _generation_process(request: Request, generation: dict[str, Any]) -> dict[str, Any]:
    store = request.app.state.store
    events = store.list_events_for_command(str(generation.get("command_id") or ""))
    state = _generation_progress(generation, events)
    failed_event = next((event for event in reversed(events) if event.get("kind") in {"generation.failed", "command.failed"}), None)
    return {
        "generation_id": generation.get("generation_id"),
        "command_id": generation.get("command_id"),
        "status": state["status"],
        "stage": state["stage"],
        "progress": state["progress"],
        "mode": generation.get("mode"),
        "engine": generation.get("engine"),
        "voice_id": generation.get("voice_id"),
        "voice_profile_id": generation.get("voice_profile_id"),
        "created_at": generation.get("created_at"),
        "updated_at": generation.get("updated_at"),
        "assets": _generation_assets(generation),
        "outcome": {
            "succeeded": state["status"] == "succeeded",
            "failed": state["status"] == "failed",
            "audio_sha256": generation.get("audio_sha256"),
            "duration_seconds": generation.get("duration_seconds"),
            "sample_rate": generation.get("sample_rate"),
            "card_id": generation.get("card_id"),
            "error": ((failed_event or {}).get("payload") or {}).get("error"),
            "engine_metadata": generation.get("engine_metadata") or {},
        },
        "timeline": events,
    }


def _is_loopback_request(request: Request) -> bool:
    host = request.client.host if request.client else ""
    if host in {"localhost", "::1"}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _safe_file(path_value: str | None, settings: Settings, allowed_roots: list[Path]) -> Path:
    if not path_value:
        raise HTTPException(status_code=404, detail="asset not found")
    path = Path(path_value).expanduser().resolve()
    allowed = [root.expanduser().resolve() for root in allowed_roots]
    if not any(path == root or root in path.parents for root in allowed):
        raise HTTPException(status_code=403, detail="asset path outside allowed roots")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="asset not found")
    return path


def _request_base_url(request: Request) -> str:
    settings: Settings = request.app.state.settings
    return f"http://{settings.host}:{settings.port}"


def _public_loopback_headers() -> dict[str, str]:
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
        "Cache-Control": "no-store",
    }


@app.get("/")
def root() -> FileResponse:
    ui_file = os.path.join(_WEB_DIR, "index.html")
    if os.path.isfile(ui_file):
        return FileResponse(ui_file, headers={"Cache-Control": "no-store"})
    raise HTTPException(status_code=404, detail="UI not found")


@app.get("/web/app.css")
def web_css() -> FileResponse:
    path = os.path.join(_WEB_DIR, "app.css")
    if os.path.isfile(path):
        return FileResponse(path, media_type="text/css", headers={"Cache-Control": "no-store"})
    raise HTTPException(status_code=404, detail="asset not found")


@app.get("/web/app.js")
def web_js() -> FileResponse:
    path = os.path.join(_WEB_DIR, "app.js")
    if os.path.isfile(path):
        return FileResponse(path, media_type="application/javascript", headers={"Cache-Control": "no-store"})
    raise HTTPException(status_code=404, detail="asset not found")


@app.get("/docs/readme")
def docs_readme(request: Request) -> dict[str, Any]:
    if not _is_loopback_request(request):
        raise HTTPException(status_code=403, detail="docs are loopback-only")
    readme_path = (_ROOT_DIR / "README.md").resolve()
    if not readme_path.is_file() or _ROOT_DIR not in readme_path.parents:
        raise HTTPException(status_code=404, detail="README.md not found")
    content = readme_path.read_text(encoding="utf-8")
    return {
        "ok": True,
        "document_id": "README.md",
        "title": "Hapa Drama README",
        "media_type": "text/markdown; charset=utf-8",
        "source_path": str(readme_path),
        "sha256": file_sha256(readme_path),
        "provenance": {
            "node": _NODE_ID,
            "surface": "api:/docs/readme",
            "served_from": "repo-root README.md",
            "generated": False,
        },
        "safe_markdown": {
            "html_passthrough": False,
            "script_execution": False,
            "link_policy": "render link text safely; open explicit http/file links in new tabs only when implemented by the UI",
            "renderer": "web/app.js safeMarkdownToHtml allowlist using textContent, not innerHTML from source Markdown",
        },
        "content": content,
    }


@app.get("/local/session")
def local_session(request: Request) -> dict[str, Any]:
    if not _is_loopback_request(request):
        raise HTTPException(status_code=403, detail="local session bootstrap is loopback-only")
    settings: Settings = request.app.state.settings
    return {
        "ok": True,
        "service": settings.service_name,
        "node": _NODE_ID,
        "api_version": settings.api_version,
        "base_url": f"http://{settings.host}:{settings.port}",
        "token": settings.token,
        "token_path": str(settings.token_file),
        "storage_dir": str(settings.storage_dir),
        "artifact_root": str(settings.artifacts_dir),
        "runtime_file": str(settings.runtime_file),
        "default_route": _current_default_route(request),
        "loopback_only": True,
    }


@app.get("/health")
def health(request: Request) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    dramabox_ready = DramaBoxEngine.readiness(settings.dramabox_python, settings.dramabox_root, allow_cpu=settings.dramabox_allow_cpu)
    return {
        "ok": True,
        "service": settings.service_name,
        "node": _NODE_ID,
        "api_version": settings.api_version,
        "base_url": f"http://{settings.host}:{settings.port}",
        "time": utc_now_iso(),
        "status": "online",
        "default_route": _current_default_route(request),
        "engines": {
            "dramabox": {
                "enabled": settings.enable_dramabox,
                "ready": bool(settings.enable_dramabox and dramabox_ready.get("ready")),
                "configured": bool(dramabox_ready.get("configured")),
                "root": dramabox_ready.get("root"),
                "python": dramabox_ready.get("python"),
                "reason": dramabox_ready.get("reason"),
            },
            "dramabox_mlx": {
                "enabled": settings.enable_mlx_dramabox,
                "ready": bool(settings.enable_mlx_dramabox and DramaBoxMLXEngine.is_available(settings.mlx_dramabox_cli)),
                "cli_path": settings.mlx_dramabox_cli,
                "model": settings.mlx_dramabox_model or "mlx-community/ResembleAI-Dramabox",
                "clone_route": "ref_audio" if settings.enable_mlx_dramabox else None,
            },
            "chatterbox": {
                "enabled": settings.enable_chatterbox,
                "ready": bool(settings.enable_chatterbox and ChatterboxEngine.is_available(settings.chatterbox_python, settings.chatterbox_root)),
                "model": settings.chatterbox_model or "standard",
                "device": settings.chatterbox_device or "auto",
                "clone_route": "audio_prompt_path" if settings.enable_chatterbox else None,
            },
            "mlx_audio": {
                "enabled": settings.enable_mlx_audio,
                "ready": MLXAudioEngine.is_available(settings.mlx_audio_cli),
                "model": settings.mlx_audio_model,
                "clone_route": "ref_audio" if settings.enable_mlx_audio else None,
            },
            "piper": {"enabled": settings.enable_piper, "ready": False},
            "macos_speech": {"enabled": settings.enable_macos_speech, "ready": MacOSSpeechEngine.is_available()},
            "stub": {"enabled": settings.stub_success, "ready": settings.stub_success},
        },
        "runtime": {"python_version": sys.version.split()[0], "pid": os.getpid()},
        "auth": {
            "bearer_required": True,
            "local_session": "/local/session",
            "query_token_enabled": bool(request.app.state.allow_query_token == "1"),
        },
    }


@app.get("/capabilities", dependencies=[Depends(_require_auth)])
def capabilities(request: Request) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    dramabox_ready = DramaBoxEngine.readiness(settings.dramabox_python, settings.dramabox_root, allow_cpu=settings.dramabox_allow_cpu)
    chatterbox_ready = ChatterboxEngine.is_available(settings.chatterbox_python, settings.chatterbox_root)
    return {
        "api_version": settings.api_version,
        "time": utc_now_iso(),
        "service": settings.service_name,
        "node": _NODE_ID,
        "feature_id": "hapa.voice.synthesis",
        "contract_version": "0.1.0",
        "capability_ids": [
            "hapa.voice.synthesis.drama",
            "hapa.voice.synthesis.flow",
            "hapa.voice.synthesis.ultrafast",
            "hapa.voice.synthesis.chatterbox",
            "hapa.voice.synthesis.dramabox",
            "hapa.voice.synthesis.dramabox_mlx",
            "hapa.voice.synthesis.macos_speech",
            "hapa.voice.cultivator.entanglement",
            "hapa.voice.profile_requests",
            "hapa.voice.reference_clip_profiles",
            "hapa.voice.default_route",
            "hapa.voice.flow_voiceover_queue",
            "hapa.cymatica.voice_layering",
            "hapa.cymatica.handoff_bundle",
            "hapa.telemetry.process_state",
        ],
        "modes": {
            "auto": {"label": "Auto", "description": "Chooses Flow for normal short text, Drama for long or high-intensity requests, or a profile default when one is selected."},
            "flow": {"label": "Flow", "description": "Fast expressive voice path. Uses Chatterbox for voice profiles when ready, legacy MLX-Audio when explicitly requested, otherwise macOS speech, then the deterministic stub."},
            "drama": {"label": "Drama", "description": "Highest-emotion/high-drama path. Uses DramaBox when enabled, otherwise macOS speech with profile identity metadata."},
            "ultrafast": {"label": "UltraFast", "description": "Lowest-latency fallback path. Uses Piper when enabled, otherwise macOS speech."},
        },
        "command_inputs": {
            "synthesize": [
                "text",
                "mode",
                "tts_engine",
                "voice_id",
                "voice_profile_id",
                "voice_clip_path",
        "chatterbox_model",
        "dramabox_cfg_scale",
        "dramabox_stg_scale",
        "dramabox_stg_block",
        "dramabox_rescale_scale",
        "dramabox_steps",
        "dramabox_gen_duration_seconds",
        "dramabox_duration_multiplier",
        "dramabox_seed",
        "emotion.style",
        "emotion.intensity",
                "timing.bpm",
                "timing.start_seconds",
                "timing.target_duration_seconds",
                "output.mint_card",
                "output.cymatica_bundle",
            ],
            "voice.profile.create": [
                "profile_id",
                "voice_id",
                "display_name",
                "description",
                "default_mode",
                "clip_generation_id",
                "clip_audio_path",
                "traits",
                "request_hints",
            ],
            "voice.profile.upload": [
                "profile_id",
                "voice_id",
                "display_name",
                "description",
                "default_mode",
                "filename",
                "clip_base64",
                "traits",
                "request_hints",
            ],
        },
        "interfaces": {
            "ui": {"enabled": True, "entry": "/", "features": ["simple_mode", "docs_readme_viewer", "record_voice", "default_route", "mode_gravity", "engine_selector", "process_timeline", "telemetry_badges", "voice_profile_upload", "voice_profiles", "script_forge", "director_track", "flow_voiceover_queue", "cymatica_handoff"]},
            "api": {"enabled": True, "version": "v1", "features": ["commands", "docs_readme", "events", "voices", "voice_profiles", "voice_profile_upload", "default_route", "flow_voiceovers", "generation_process", "generations", "assets", "peers", "telemetry"]},
            "cli": {"enabled": True, "binary": "hapa-drama", "features": ["serve", "docs", "health", "capabilities", "synthesize", "voice-create", "voice-profile-create", "voice-profiles", "voices", "self-test", "cymatica-validate", "cymatica-handoff-validate"]},
        },
        "hapa_protocol": {
            "command_envelope": "v1",
            "ui_cli_api_parity": True,
            "loopback_bearer_auth": True,
            "local_session": True,
            "process_telemetry": True,
            "audible_wav_validation": True,
            "card_provenance": True,
            "cymatica_handoff": True,
        },
        "default_route": _current_default_route(request),
        "api": {
            "health": "/health",
            "local_session": "/local/session",
            "docs_readme": "/docs/readme",
            "capabilities": "/capabilities",
            "commands": "/v1/commands",
            "events": "/v1/events",
            "voices": "/v1/voices",
            "voice_profiles": "/v1/voice-profiles",
            "default_route": "/v1/default-route",
            "generations": "/v1/generations",
            "generation_process": "/v1/generations/{generation_id}/process",
            "audio": "/v1/generations/{generation_id}/audio",
            "flow_voiceovers": "/v1/flow-voiceovers/queue",
            "flow_voiceover_manifest": "/v1/flow-voiceovers/{flow_id}/manifest",
            "peers": "/v1/peers",
            "telemetry": "/v1/telemetry",
        },
        "engines": {
            "dramabox": {
                "backend": "DramaBox",
                "enabled": settings.enable_dramabox,
                "ready": bool(settings.enable_dramabox and dramabox_ready.get("ready")),
                "configured": bool(dramabox_ready.get("configured")),
                "model": "ResembleAI/Dramabox",
                "voice_clone_supported": bool(dramabox_ready.get("ready")),
                "reason": dramabox_ready.get("reason"),
            },
            "dramabox_mlx": {
                "backend": "DramaBox MLX",
                "enabled": settings.enable_mlx_dramabox,
                "ready": bool(settings.enable_mlx_dramabox and DramaBoxMLXEngine.is_available(settings.mlx_dramabox_cli)),
                "model": settings.mlx_dramabox_model or "mlx-community/ResembleAI-Dramabox",
                "voice_clone_supported": bool(settings.enable_mlx_dramabox and DramaBoxMLXEngine.is_available(settings.mlx_dramabox_cli)),
                "watermarking": "skipped_by_mlx_conversion",
            },
            "chatterbox": {
                "backend": "Chatterbox",
                "enabled": settings.enable_chatterbox,
                "ready": bool(settings.enable_chatterbox and chatterbox_ready),
                "model": settings.chatterbox_model or "standard",
                "device": settings.chatterbox_device or "auto",
                "voice_clone_supported": bool(settings.enable_chatterbox and chatterbox_ready),
            },
            "drama": {
                "backend": "DramaBox MLX" if settings.enable_mlx_dramabox else "DramaBox",
                "enabled": bool(settings.enable_mlx_dramabox or settings.enable_dramabox),
                "ready": bool(
                    (settings.enable_mlx_dramabox and DramaBoxMLXEngine.is_available(settings.mlx_dramabox_cli))
                    or (settings.enable_dramabox and dramabox_ready.get("ready"))
                ),
            },
            "flow": {
                "backend": "MLX-Audio",
                "enabled": settings.enable_mlx_audio,
                "ready": MLXAudioEngine.is_available(settings.mlx_audio_cli),
                "model": settings.mlx_audio_model,
                "voice_clone_supported": bool(settings.enable_mlx_audio and MLXAudioEngine.is_available(settings.mlx_audio_cli)),
            },
            "ultrafast": {"backend": "Piper", "enabled": settings.enable_piper},
            "macos_speech": {
                "backend": "macOS say/afconvert",
                "enabled": settings.enable_macos_speech,
                "ready": MacOSSpeechEngine.is_available(),
                "default_voice": settings.macos_voice,
            },
            "stub": {"backend": "deterministic wav stub", "enabled": settings.stub_success},
        },
        "hapa_connectivity": _peers_payload(settings)["peers"],
    }


@app.post("/v1/commands", dependencies=[Depends(_require_auth)])
def post_command(body: CommandRequest, request: Request) -> dict[str, Any]:
    try:
        result = request.app.state.router.dispatch(body.model_dump())
        generation = result.get("generation") if isinstance(result, dict) else None
        if isinstance(generation, dict) and generation.get("generation_id"):
            result["process"] = _generation_process(request, generation)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/v1/events", dependencies=[Depends(_require_auth)])
def get_events(request: Request, since: int = 0, limit: int = 100) -> dict[str, Any]:
    return {"ok": True, "events": request.app.state.store.list_events(since=since, limit=limit)}


@app.get("/v1/voices", dependencies=[Depends(_require_auth)])
def get_voices(request: Request) -> dict[str, Any]:
    return {"ok": True, "voices": request.app.state.store.list_voices()}


@app.get("/v1/voice-profiles", dependencies=[Depends(_require_auth)])
def get_voice_profiles(request: Request) -> dict[str, Any]:
    return {"ok": True, "voice_profiles": request.app.state.store.list_voice_profiles()}


@app.get("/v1/default-route", dependencies=[Depends(_require_auth)])
def get_default_route(request: Request) -> dict[str, Any]:
    return {"ok": True, "default_route": _current_default_route(request)}


@app.put("/v1/default-route", dependencies=[Depends(_require_auth)])
def put_default_route(body: DefaultRouteRequest, request: Request) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    store: DramaStore = request.app.state.store
    raw = body.model_dump(exclude_none=True)
    profile_id = str(raw.get("voice_profile_id") or "").strip()
    if profile_id and not store.get_voice_profile(profile_id):
        raise HTTPException(status_code=404, detail="voice_profile_id not found")
    route = _normalize_default_route(settings, store, raw)
    _save_default_route(settings, route)
    request.app.state.default_route = route
    request.app.state.router.set_default_route(route)
    return {"ok": True, "default_route": route, "path": str(settings.default_route_file)}


@app.post("/v1/flow-voiceovers/queue", dependencies=[Depends(_require_auth)])
def queue_flow_voiceovers(body: FlowVoiceoverQueueRequest, request: Request) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    raw = body.model_dump(exclude_none=True)
    default_route = _current_default_route(request)
    raw.setdefault("mode", "drama")
    raw.setdefault("tts_engine", "dramabox")
    if raw.get("use_default_voice", True):
        for key in ("voice_profile_id", "voice_id", "voice_clip_path"):
            if not raw.get(key) and default_route.get(key):
                raw[key] = default_route[key]
    try:
        manifest = build_flow_voiceover_manifest(settings, raw, base_url=_request_base_url(request))
        if body.process:
            manifest = process_flow_voiceover_queue(
                settings,
                request.app.state.router,
                manifest,
                force=body.force,
                base_url=_request_base_url(request),
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "flow_voiceover": manifest}


@app.get("/v1/flow-voiceovers/{flow_id}", dependencies=[Depends(_require_auth)])
def get_flow_voiceover(flow_id: str, request: Request) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    manifest = read_flow_voiceover_manifest(settings, flow_id)
    if not manifest:
        raise HTTPException(status_code=404, detail="flow voiceover manifest not found")
    return {"ok": True, "flow_voiceover": with_public_urls(manifest, _request_base_url(request))}


@app.post("/v1/flow-voiceovers/{flow_id}/process", dependencies=[Depends(_require_auth)])
def process_flow_voiceovers(flow_id: str, body: FlowVoiceoverProcessRequest, request: Request) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    manifest = read_flow_voiceover_manifest(settings, flow_id)
    if not manifest:
        raise HTTPException(status_code=404, detail="flow voiceover manifest not found")
    manifest = process_flow_voiceover_queue(
        settings,
        request.app.state.router,
        manifest,
        force=body.force,
        base_url=_request_base_url(request),
    )
    return {"ok": True, "flow_voiceover": manifest}


@app.get("/v1/flow-voiceovers/{flow_id}/manifest")
def get_public_flow_voiceover_manifest(flow_id: str, request: Request) -> JSONResponse:
    if not _is_loopback_request(request):
        raise HTTPException(status_code=403, detail="flow voiceover manifests are loopback-only")
    settings: Settings = request.app.state.settings
    manifest = read_flow_voiceover_manifest(settings, flow_id)
    if not manifest:
        raise HTTPException(status_code=404, detail="flow voiceover manifest not found")
    return JSONResponse(
        {"ok": True, "flow_voiceover": with_public_urls(manifest, _request_base_url(request))},
        headers=_public_loopback_headers(),
    )


@app.get("/v1/flow-voiceovers/{flow_id}/steps/{step_key}/audio")
def get_public_flow_voiceover_audio(flow_id: str, step_key: str, request: Request) -> FileResponse:
    if not _is_loopback_request(request):
        raise HTTPException(status_code=403, detail="flow voiceover audio is loopback-only")
    settings: Settings = request.app.state.settings
    path = flow_voiceover_audio_path(settings, safe_flow_id(flow_id), safe_flow_id(step_key))
    if not path.is_file():
        raise HTTPException(status_code=404, detail="flow voiceover audio not found")
    return FileResponse(path, media_type="audio/wav", filename=f"{safe_flow_id(flow_id)}-{safe_flow_id(step_key)}.wav", headers=_public_loopback_headers())


@app.post("/v1/voice-profiles/upload", dependencies=[Depends(_require_auth)])
def upload_voice_profile_clip(body: VoiceProfileUploadRequest, request: Request) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    normalized_mode = str(body.default_mode or "auto").strip().lower()
    if normalized_mode not in {"auto", "drama", "flow", "ultrafast"}:
        raise HTTPException(status_code=400, detail="default_mode must be one of: auto, drama, flow, ultrafast")
    safe_profile_id = str(body.profile_id or f"profile-{uuid.uuid4()}").strip()
    safe_voice_id = str(body.voice_id or f"voice-{safe_profile_id}").strip()
    suffix = Path(body.filename or "voice.wav").suffix.lower() or ".wav"
    if suffix not in {".wav", ".aif", ".aiff", ".caf", ".m4a", ".mp3", ".flac", ".ogg"}:
        raise HTTPException(status_code=400, detail="voice clip must be an audio file")
    try:
        raw = base64.b64decode(body.clip_base64, validate=True)
    except Exception:
        raise HTTPException(status_code=400, detail="clip_base64 is not valid base64")
    if len(raw) <= 44:
        raise HTTPException(status_code=400, detail="voice clip is empty or too small")
    out_dir = settings.artifacts_dir / "voice_profiles" / safe_profile_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"clip{suffix}"
    out_path.write_bytes(raw)
    sha = file_sha256(out_path)
    voice = request.app.state.store.get_voice(safe_voice_id) or request.app.state.store.create_voice(safe_voice_id, body.display_name, {"source": "uploaded_clip"})
    profile = request.app.state.store.create_voice_profile(
        {
            "profile_id": safe_profile_id,
            "voice_id": safe_voice_id,
            "display_name": body.display_name,
            "description": body.description,
            "default_mode": normalized_mode,
            "clip_audio_path": str(out_path),
            "clip_audio_sha256": sha,
            "traits": {"source": "uploaded_clip", "filename": body.filename or out_path.name, **(body.traits or {})},
            "request_hints": {"clip_source": "ui_upload", **(body.request_hints or {})},
            "created_by": "web-ui:upload",
        }
    )
    return {"ok": True, "voice": voice, "voice_profile": profile}


@app.get("/v1/voice-profiles/{profile_id}", dependencies=[Depends(_require_auth)])
def get_voice_profile(profile_id: str, request: Request) -> dict[str, Any]:
    profile = request.app.state.store.get_voice_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="voice profile not found")
    return {"ok": True, "voice_profile": profile}


@app.get("/v1/voice-profiles/{profile_id}/clip", dependencies=[Depends(_require_auth)])
def get_voice_profile_clip(profile_id: str, request: Request) -> FileResponse:
    settings: Settings = request.app.state.settings
    profile = request.app.state.store.get_voice_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="voice profile not found")
    path = _safe_file(profile.get("clip_audio_path"), settings, [settings.artifacts_dir])
    return FileResponse(path, media_type="audio/wav", filename=f"{profile_id}{path.suffix or '.wav'}")


@app.get("/v1/generations", dependencies=[Depends(_require_auth)])
def get_generations(request: Request, limit: int = 50) -> dict[str, Any]:
    generations = request.app.state.store.list_generations(limit=limit)
    return {"ok": True, "generations": generations, "processes": [_generation_process(request, generation) for generation in generations]}


@app.get("/v1/generations/{generation_id}", dependencies=[Depends(_require_auth)])
def get_generation(generation_id: str, request: Request) -> dict[str, Any]:
    generation = _generation_or_404(request, generation_id)
    return {"ok": True, "generation": generation}


@app.get("/v1/generations/{generation_id}/process", dependencies=[Depends(_require_auth)])
def get_generation_process(generation_id: str, request: Request) -> dict[str, Any]:
    generation = _generation_or_404(request, generation_id)
    return {"ok": True, "process": _generation_process(request, generation)}


@app.get("/v1/generations/{generation_id}/audio", dependencies=[Depends(_require_auth)])
def get_generation_audio(generation_id: str, request: Request) -> FileResponse:
    settings: Settings = request.app.state.settings
    generation = _generation_or_404(request, generation_id)
    audio_path = _safe_file(generation.get("audio_path"), settings, [settings.artifacts_dir])
    return FileResponse(audio_path, media_type="audio/wav", filename=f"{generation_id}.wav")


@app.get("/v1/generations/{generation_id}/card", dependencies=[Depends(_require_auth)])
def get_generation_card(generation_id: str, request: Request) -> FileResponse:
    settings: Settings = request.app.state.settings
    generation = _generation_or_404(request, generation_id)
    card_id = str(generation.get("card_id") or "").strip()
    if not card_id:
        raise HTTPException(status_code=404, detail="card not found")
    card_path = settings.artifacts_dir / "cards" / card_id / "card.json"
    path = _safe_file(str(card_path), settings, [settings.artifacts_dir])
    return FileResponse(path, media_type="application/json", filename=f"{card_id}.json")


@app.get("/v1/generations/{generation_id}/cymatica-manifest", dependencies=[Depends(_require_auth)])
def get_generation_cymatica_manifest(generation_id: str, request: Request) -> FileResponse:
    settings: Settings = request.app.state.settings
    generation = _generation_or_404(request, generation_id)
    bundle_path = str(generation.get("cymatica_bundle_path") or "").strip()
    if not bundle_path:
        raise HTTPException(status_code=404, detail="cymatica bundle not found")
    manifest_path = Path(bundle_path) / "cymatica_manifest.json"
    path = _safe_file(str(manifest_path), settings, [settings.artifacts_dir])
    return FileResponse(path, media_type="application/json", filename=f"{generation_id}-cymatica-manifest.json")


@app.get("/v1/generations/{generation_id}/cymatica-handoff", dependencies=[Depends(_require_auth)])
def get_generation_cymatica_handoff(generation_id: str, request: Request) -> FileResponse:
    settings: Settings = request.app.state.settings
    generation = _generation_or_404(request, generation_id)
    path = _safe_file(generation.get("cymatica_handoff_zip_path"), settings, [settings.artifacts_dir])
    return FileResponse(path, media_type="application/zip", filename=f"{generation_id}.hapaBundle.zip")


@app.get("/v1/peers", dependencies=[Depends(_require_auth)])
def peers(request: Request) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    return {"api_version": settings.api_version, "time": utc_now_iso(), "service": settings.service_name, "node": _NODE_ID, **_peers_payload(settings)}


@app.get("/v1/telemetry", dependencies=[Depends(_require_auth)])
def telemetry(request: Request) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    store = request.app.state.store
    generations = request.app.state.store.list_generations(limit=1000)
    recent = request.app.state.store.list_generations(limit=10)
    counts: dict[str, int] = {}
    for generation in generations:
        status = str(generation.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    flow_counts = flow_voiceover_queue_counts(settings)
    return {
        "ok": True,
        "service": settings.service_name,
        "node": _NODE_ID,
        "node_id": settings.service_name,
        "api_version": settings.api_version,
        "base_url": f"http://{settings.host}:{settings.port}",
        "timestamp": utc_now_iso(),
        "status": "online",
        "health": {"status": "healthy"},
        "metrics": {
            "queue_depth": flow_counts["queued"] + flow_counts["running"],
            "running": len([g for g in generations if g.get("status") == "running"]),
            "tasks_completed": len([g for g in generations if g.get("status") == "succeeded"]),
            "tasks_failed": len([g for g in generations if g.get("status") == "failed"]),
            "generation_counts": counts,
            "flow_voiceover_queue": flow_counts,
            "voice_profile_count": len(store.list_voice_profiles()),
            "voice_count": len(store.list_voices()),
            "latest_event_seq": store.latest_event_seq(),
        },
        "recent_processes": [_generation_process(request, generation) for generation in recent],
        "capabilities": {"service_type": "media", "modalities": {"audio": True, "voice": True}},
    }
