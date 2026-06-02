from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from .audio import assert_audible_wav
from .card_mint import mint_audio_card
from .config import Settings, utc_now_iso
from .cymatica import write_cymatica_bundle
from .engines.chatterbox_adapter import ChatterboxEngine
from .engines.dramabox_adapter import DramaBoxEngine
from .engines.macos_speech_adapter import MacOSSpeechEngine
from .engines.mlx_audio_adapter import DramaBoxMLXEngine, MLXAudioEngine
from .engines.piper_adapter import PiperEngine
from .engines.stub_adapter import StubDramaEngine
from .models import DramaCommand
from .persistence import DramaStore
from .provenance import file_sha256, stable_json_hash


class DramaRouter:
    def __init__(self, settings: Settings, store: DramaStore) -> None:
        self.settings = settings
        self.store = store
        self.default_route: dict[str, Any] = {}

    def set_default_route(self, route: dict[str, Any] | None) -> None:
        self.default_route = dict(route or {})

    def _event(self, command_id: str, kind: str, sequence: int, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        event = {
            "event_id": str(uuid.uuid4()),
            "command_id": command_id,
            "kind": kind,
            "sequence": sequence,
            "time": utc_now_iso(),
            "payload": payload or {},
        }
        self.store.append_event(event)
        return event

    def dispatch(self, data: dict[str, Any]) -> dict[str, Any]:
        command = DramaCommand.from_dict(data)
        if command.kind == "synthesize":
            return self._synthesize(command)
        if command.kind == "voice.create":
            return self._voice_create(command)
        if command.kind == "voice.profile.create":
            return self._voice_profile_create(command)
        if command.kind == "voice.profile.get":
            return self._voice_profile_get(command)
        if command.kind == "voice.profile.list":
            return {"ok": True, "voice_profiles": self.store.list_voice_profiles(), "events": []}
        if command.kind == "voice.entangle":
            return self._voice_entangle(command)
        if command.kind == "generation.get":
            generation_id = str(command.payload.get("generation_id") or "").strip()
            return {"ok": True, "generation": self.store.get_generation(generation_id), "events": []}
        if command.kind == "generation.list":
            return {"ok": True, "generations": self.store.list_generations(), "events": []}
        raise ValueError(f"Unsupported command kind: {command.kind}")

    def _select_engine(self, mode: str, payload: dict[str, Any]):
        requested_engine = str(
            payload.get("tts_engine")
            or payload.get("engine")
            or payload.get("voice_engine")
            or payload.get("backend")
            or ""
        ).strip().lower().replace("_", "-")
        if requested_engine in {"chatterbox", "chatterbox-tts"}:
            if not self.settings.enable_chatterbox:
                raise RuntimeError("Chatterbox engine was requested but HAPA_DRAMA_ENABLE_CHATTERBOX is not enabled")
            return ChatterboxEngine(
                python_path=self.settings.chatterbox_python,
                root_path=self.settings.chatterbox_root,
                device=self.settings.chatterbox_device,
                model=self.settings.chatterbox_model,
                timeout_seconds=self.settings.chatterbox_timeout_seconds,
                exaggeration=self.settings.chatterbox_exaggeration,
                cfg_weight=self.settings.chatterbox_cfg_weight,
                temperature=self.settings.chatterbox_temperature,
            )
        if requested_engine in {"dramabox", "drama-box"}:
            if self.settings.enable_mlx_dramabox and DramaBoxMLXEngine.is_available(self.settings.mlx_dramabox_cli):
                return DramaBoxMLXEngine(
                    cli_path=self.settings.mlx_dramabox_cli,
                    model=self.settings.mlx_dramabox_model,
                    ref_text=self.settings.mlx_dramabox_ref_text,
                    timeout_seconds=self.settings.mlx_dramabox_timeout_seconds,
                    cfg_scale=self.settings.mlx_dramabox_cfg_scale,
                    stg_scale=self.settings.mlx_dramabox_stg_scale,
                    steps=self.settings.mlx_dramabox_steps,
                    gen_duration_seconds=self.settings.mlx_dramabox_gen_duration_seconds,
                )
            if not self.settings.enable_dramabox:
                raise RuntimeError("DramaBox engine was requested but neither HAPA_DRAMA_ENABLE_MLX_DRAMABOX nor HAPA_DRAMA_ENABLE_DRAMABOX is ready")
            return DramaBoxEngine(
                python_path=self.settings.dramabox_python,
                root_path=self.settings.dramabox_root,
                device=self.settings.dramabox_device,
                timeout_seconds=self.settings.dramabox_timeout_seconds,
                cfg_scale=self.settings.dramabox_cfg_scale,
                stg_scale=self.settings.dramabox_stg_scale,
                allow_cpu=self.settings.dramabox_allow_cpu,
            )
        if requested_engine in {"dramabox-mlx", "drama-box-mlx", "mlx-dramabox"}:
            if not self.settings.enable_mlx_dramabox:
                raise RuntimeError("DramaBox MLX engine was requested but HAPA_DRAMA_ENABLE_MLX_DRAMABOX is not enabled")
            return DramaBoxMLXEngine(
                cli_path=self.settings.mlx_dramabox_cli,
                model=self.settings.mlx_dramabox_model,
                ref_text=self.settings.mlx_dramabox_ref_text,
                timeout_seconds=self.settings.mlx_dramabox_timeout_seconds,
                cfg_scale=self.settings.mlx_dramabox_cfg_scale,
                stg_scale=self.settings.mlx_dramabox_stg_scale,
                steps=self.settings.mlx_dramabox_steps,
                gen_duration_seconds=self.settings.mlx_dramabox_gen_duration_seconds,
            )
        if requested_engine in {"dramabox-cuda", "drama-box-cuda", "dramabox-pytorch"}:
            if not self.settings.enable_dramabox:
                raise RuntimeError("DramaBox CUDA engine was requested but HAPA_DRAMA_ENABLE_DRAMABOX is not enabled")
            return DramaBoxEngine(
                python_path=self.settings.dramabox_python,
                root_path=self.settings.dramabox_root,
                device=self.settings.dramabox_device,
                timeout_seconds=self.settings.dramabox_timeout_seconds,
                cfg_scale=self.settings.dramabox_cfg_scale,
                stg_scale=self.settings.dramabox_stg_scale,
                allow_cpu=self.settings.dramabox_allow_cpu,
            )
        if requested_engine in {"mlx-audio", "mlx", "indextts", "index-tts"}:
            if not self.settings.enable_mlx_audio:
                raise RuntimeError("MLX-Audio engine was requested but HAPA_DRAMA_ENABLE_MLX_AUDIO is not enabled")
            return MLXAudioEngine(
                cli_path=self.settings.mlx_audio_cli,
                model=self.settings.mlx_audio_model,
                ref_text=self.settings.mlx_audio_ref_text,
                timeout_seconds=self.settings.mlx_audio_timeout_seconds,
            )
        if requested_engine in {"macos-speech", "macos", "say"}:
            if not self.settings.enable_macos_speech or not MacOSSpeechEngine.is_available():
                raise RuntimeError("macOS speech engine was requested but it is not available")
            return MacOSSpeechEngine(default_voice=self.settings.macos_voice, default_rate_wpm=self.settings.macos_rate_wpm)
        if requested_engine:
            raise RuntimeError(f"Unknown TTS engine requested: {requested_engine}")

        if mode == "drama" and self.settings.enable_mlx_dramabox and DramaBoxMLXEngine.is_available(self.settings.mlx_dramabox_cli):
            return DramaBoxMLXEngine(
                cli_path=self.settings.mlx_dramabox_cli,
                model=self.settings.mlx_dramabox_model,
                ref_text=self.settings.mlx_dramabox_ref_text,
                timeout_seconds=self.settings.mlx_dramabox_timeout_seconds,
                cfg_scale=self.settings.mlx_dramabox_cfg_scale,
                stg_scale=self.settings.mlx_dramabox_stg_scale,
                steps=self.settings.mlx_dramabox_steps,
                gen_duration_seconds=self.settings.mlx_dramabox_gen_duration_seconds,
            )
        if mode == "drama" and self.settings.enable_dramabox and DramaBoxEngine.readiness(
            self.settings.dramabox_python,
            self.settings.dramabox_root,
            allow_cpu=self.settings.dramabox_allow_cpu,
        ).get("ready"):
            return DramaBoxEngine(
                python_path=self.settings.dramabox_python,
                root_path=self.settings.dramabox_root,
                device=self.settings.dramabox_device,
                timeout_seconds=self.settings.dramabox_timeout_seconds,
                cfg_scale=self.settings.dramabox_cfg_scale,
                stg_scale=self.settings.dramabox_stg_scale,
                allow_cpu=self.settings.dramabox_allow_cpu,
            )
        voice_clip_path = str(payload.get("voice_clip_path") or "").strip()
        force_mlx_audio = bool(payload.get("force_mlx_audio"))
        if mode == "flow" and self.settings.enable_mlx_audio and (voice_clip_path or force_mlx_audio):
            if voice_clip_path and self.settings.enable_chatterbox and not force_mlx_audio:
                return ChatterboxEngine(
                    python_path=self.settings.chatterbox_python,
                    root_path=self.settings.chatterbox_root,
                    device=self.settings.chatterbox_device,
                    model=self.settings.chatterbox_model,
                    timeout_seconds=self.settings.chatterbox_timeout_seconds,
                    exaggeration=self.settings.chatterbox_exaggeration,
                    cfg_weight=self.settings.chatterbox_cfg_weight,
                    temperature=self.settings.chatterbox_temperature,
                )
            return MLXAudioEngine(
                cli_path=self.settings.mlx_audio_cli,
                model=self.settings.mlx_audio_model,
                ref_text=self.settings.mlx_audio_ref_text,
                timeout_seconds=self.settings.mlx_audio_timeout_seconds,
            )
        if mode == "flow" and self.settings.enable_chatterbox and voice_clip_path:
            return ChatterboxEngine(
                python_path=self.settings.chatterbox_python,
                root_path=self.settings.chatterbox_root,
                device=self.settings.chatterbox_device,
                model=self.settings.chatterbox_model,
                timeout_seconds=self.settings.chatterbox_timeout_seconds,
                exaggeration=self.settings.chatterbox_exaggeration,
                cfg_weight=self.settings.chatterbox_cfg_weight,
                temperature=self.settings.chatterbox_temperature,
            )
        if mode == "ultrafast" and self.settings.enable_piper:
            return PiperEngine()
        if self.settings.enable_macos_speech and MacOSSpeechEngine.is_available():
            return MacOSSpeechEngine(default_voice=self.settings.macos_voice, default_rate_wpm=self.settings.macos_rate_wpm)
        if self.settings.stub_success:
            return StubDramaEngine()
        raise RuntimeError("No Hapa Drama synthesis engine is available")

    def _apply_default_route(self, payload: dict[str, Any]) -> None:
        route = self.default_route or {}
        default_tts_engine = str(route.get("tts_engine") or self.settings.default_tts_engine or "").strip()
        default_voice_profile_id = str(route.get("voice_profile_id") or self.settings.default_voice_profile_id or "").strip()
        default_voice_clip_path = str(route.get("voice_clip_path") or self.settings.default_voice_clip_path or "").strip()
        default_voice_id = str(route.get("voice_id") or self.settings.default_voice_id or "").strip()
        default_ref_text = str(route.get("reference_text") or "").strip()
        default_ref_text_is_transcript = str(route.get("reference_text_is_transcript") or "").strip().lower() in {"1", "true", "yes", "on"}
        use_default_voice = str(payload.get("use_default_voice", "true")).strip().lower() not in {"0", "false", "no", "off"}
        skip_default_route = str(payload.get("skip_default_route") or payload.get("no_default_route") or "").strip().lower() in {"1", "true", "yes", "on"}
        default_engine_available = (
            default_tts_engine not in {"dramabox", "drama-box", "dramabox-mlx", "mlx-dramabox"}
            or self.settings.enable_mlx_dramabox
            or self.settings.enable_dramabox
        )
        if (
            not skip_default_route
            and default_tts_engine
            and default_engine_available
            and not any(str(payload.get(key) or "").strip() for key in ("tts_engine", "engine", "voice_engine", "backend"))
        ):
            payload["tts_engine"] = default_tts_engine
        if skip_default_route or not use_default_voice:
            return
        if (
            default_voice_profile_id
            and self.store.get_voice_profile(default_voice_profile_id)
            and not any(str(payload.get(key) or "").strip() for key in ("voice_profile_id", "profile_id", "voice_clip_path"))
        ):
            payload["voice_profile_id"] = default_voice_profile_id
        elif default_voice_clip_path and not any(str(payload.get(key) or "").strip() for key in ("voice_profile_id", "profile_id", "voice_clip_path")):
            payload["voice_clip_path"] = default_voice_clip_path
        if default_voice_id and self.store.get_voice(default_voice_id) and not str(payload.get("voice_id") or "").strip():
            payload["voice_id"] = default_voice_id
        if default_ref_text_is_transcript and default_ref_text and not any(str(payload.get(key) or "").strip() for key in ("ref_text", "reference_text", "voice_clip_text")):
            payload["ref_text"] = default_ref_text

    def _resolve_voice_request(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        profile_id = str(payload.get("voice_profile_id") or payload.get("profile_id") or "").strip()
        profile = None
        if profile_id:
            profile = self.store.get_voice_profile(profile_id)
            if not profile:
                raise ValueError("voice_profile_id not found")
            payload["voice_profile_id"] = profile_id
            if not str(payload.get("voice_id") or "").strip():
                payload["voice_id"] = profile.get("voice_id")
            payload["voice_profile"] = {
                "profile_id": profile.get("profile_id"),
                "display_name": profile.get("display_name"),
                "default_mode": profile.get("default_mode"),
                "clip_generation_id": profile.get("clip_generation_id"),
                "clip_audio_path": profile.get("clip_audio_path"),
                "clip_audio_sha256": profile.get("clip_audio_sha256"),
                "traits": profile.get("traits") or {},
                "request_hints": profile.get("request_hints") or {},
            }
            if not str(payload.get("voice_clip_path") or "").strip():
                payload["voice_clip_path"] = profile.get("clip_audio_path")
        voice_id = str(payload.get("voice_id") or "").strip()
        if voice_id and not self.store.get_voice(voice_id):
            raise ValueError("voice_id not found")
        return profile

    def _synthesize(self, command: DramaCommand) -> dict[str, Any]:
        payload = dict(command.payload)
        text = str(payload.get("text") or payload.get("script") or "").strip()
        if not text:
            raise ValueError("payload.text is required for synthesize")
        self._apply_default_route(payload)
        profile = self._resolve_voice_request(payload)
        events = [self._event(command.command_id, "command.accepted", 1, {"kind": command.kind})]
        profile_mode = str((profile or {}).get("default_mode") or "").lower()
        route_mode = str((self.default_route or {}).get("mode") or "").lower()
        configured_default_mode = route_mode or self.settings.default_mode
        default_mode = configured_default_mode if configured_default_mode in {"drama", "flow", "ultrafast"} else ""
        mode = command.mode if command.mode != "auto" else (profile_mode if profile_mode in {"drama", "flow", "ultrafast"} else (default_mode or self._auto_mode(payload)))
        engine = self._select_engine(mode, payload)
        events.append(self._event(command.command_id, "engine.selected", 2, {"mode": mode, "engine": engine.name, "voice_id": payload.get("voice_id"), "voice_profile_id": payload.get("voice_profile_id")}))
        generation_id = str(uuid.uuid4())
        out_dir = self.settings.artifacts_dir / "generations" / generation_id
        audio_path = out_dir / "voice.wav"
        text_hash = stable_json_hash({"text": text})
        voice_id = str(payload.get("voice_id") or "").strip() or None
        voice_profile_id = str(payload.get("voice_profile_id") or "").strip() or None
        self.store.upsert_generation(
            {
                "generation_id": generation_id,
                "command_id": command.command_id,
                "mode": mode,
                "engine": engine.name,
                "status": "running",
                "text_hash": text_hash,
                "voice_id": voice_id,
                "voice_profile_id": voice_profile_id,
                "created_at": utc_now_iso(),
            }
        )
        events.append(self._event(command.command_id, "generation.started", 3, {"generation_id": generation_id, "voice_id": voice_id, "voice_profile_id": voice_profile_id}))
        try:
            result = engine.synthesize(text=text, output_path=audio_path, payload=payload)
            inspection = assert_audible_wav(
                result.audio_path,
                min_duration_seconds=self.settings.min_audio_duration_seconds,
                min_normalized_rms=self.settings.min_audio_normalized_rms,
            )
            audio_sha = file_sha256(result.audio_path)
            generation = {
                "generation_id": generation_id,
                "command_id": command.command_id,
                "mode": mode,
                "engine": result.engine,
                "status": "succeeded",
                "text_hash": text_hash,
                "audio_path": str(result.audio_path),
                "audio_sha256": audio_sha,
                "duration_seconds": inspection.duration_seconds,
                "sample_rate": inspection.sample_rate,
                "engine_metadata": result.metadata,
                "voice_id": voice_id,
                "voice_profile_id": voice_profile_id,
                "created_at": utc_now_iso(),
            }
            normalized_command = command.to_dict()
            normalized_command["mode"] = mode
            normalized_command["payload"] = payload
            card_info: dict[str, Any] | None = None
            if bool(payload.get("output", {}).get("mint_card", True)):
                card_info = mint_audio_card(self.settings, generation, normalized_command)
                generation["card_id"] = card_info["card_id"]
            cymatica_info: dict[str, Any] | None = None
            if bool(payload.get("output", {}).get("cymatica_bundle", True)):
                cymatica_info = write_cymatica_bundle(self.settings, generation, normalized_command)
                generation["cymatica_bundle_path"] = cymatica_info["bundle_path"]
                generation["cymatica_handoff_path"] = cymatica_info["handoff_path"]
                generation["cymatica_handoff_zip_path"] = cymatica_info["handoff_zip_path"]
            self.store.upsert_generation(generation)
            events.append(self._event(command.command_id, "asset.written", 4, {"audio_path": str(result.audio_path), "sha256": audio_sha}))
            events.append(
                self._event(
                    command.command_id,
                    "asset.validated",
                    5,
                    {
                        "duration_seconds": round(inspection.duration_seconds, 3),
                        "sample_rate": inspection.sample_rate,
                        "normalized_rms": round(inspection.normalized_rms, 6),
                    },
                )
            )
            if card_info:
                events.append(self._event(command.command_id, "card.minted", 6, {"card_id": card_info["card_id"], "card_path": card_info["card_path"]}))
            if cymatica_info:
                events.append(self._event(command.command_id, "cymatica.bundle.written", 7, {"manifest_path": cymatica_info["manifest_path"], "handoff_zip_path": cymatica_info["handoff_zip_path"]}))
            events.append(self._event(command.command_id, "generation.completed", 8, {"generation_id": generation_id, "status": "succeeded"}))
            if voice_id:
                try:
                    voice = self.store.entangle_voice(voice_id, 10)
                    events.append(self._event(command.command_id, "voice.entanglement.updated", 9, {"voice": voice}))
                except ValueError:
                    pass
            return {"ok": True, "generation": generation, "events": events}
        except Exception as exc:
            self.store.upsert_generation(
                {
                    "generation_id": generation_id,
                    "command_id": command.command_id,
                    "mode": mode,
                    "engine": getattr(engine, "name", "unknown"),
                    "status": "failed",
                    "text_hash": text_hash,
                    "voice_id": voice_id,
                    "voice_profile_id": voice_profile_id,
                    "created_at": utc_now_iso(),
                }
            )
            events.append(self._event(command.command_id, "generation.failed", 8, {"generation_id": generation_id, "status": "failed", "error": str(exc)}))
            events.append(self._event(command.command_id, "command.failed", 9, {"error": str(exc), "generation_id": generation_id}))
            raise

    def _auto_mode(self, payload: dict[str, Any]) -> str:
        text = str(payload.get("text") or payload.get("script") or "")
        emotion = payload.get("emotion") if isinstance(payload.get("emotion"), dict) else {}
        intensity = float((emotion or {}).get("intensity") or 0)
        if len(text) > 500 or intensity >= 0.7:
            return "drama"
        return "flow"

    def _voice_create(self, command: DramaCommand) -> dict[str, Any]:
        display_name = str(command.payload.get("display_name") or command.payload.get("name") or "").strip()
        if not display_name:
            raise ValueError("payload.display_name is required")
        voice_id = str(command.payload.get("voice_id") or f"voice-{uuid.uuid4()}").strip()
        voice = self.store.create_voice(voice_id, display_name, command.payload.get("traits") if isinstance(command.payload.get("traits"), dict) else {})
        event = self._event(command.command_id, "voice.created", 1, {"voice": voice})
        return {"ok": True, "voice": voice, "events": [event]}

    def _voice_profile_create(self, command: DramaCommand) -> dict[str, Any]:
        display_name = str(command.payload.get("display_name") or command.payload.get("name") or "").strip()
        if not display_name:
            raise ValueError("payload.display_name is required")
        profile_id = str(command.payload.get("voice_profile_id") or command.payload.get("profile_id") or f"profile-{uuid.uuid4()}").strip()
        voice_id = str(command.payload.get("voice_id") or f"voice-{profile_id}").strip()
        default_mode = str(command.payload.get("default_mode") or "auto").strip().lower()
        if default_mode not in {"auto", "drama", "flow", "ultrafast"}:
            raise ValueError("payload.default_mode must be one of: auto, drama, flow, ultrafast")
        traits = command.payload.get("traits") if isinstance(command.payload.get("traits"), dict) else {}
        voice = self.store.get_voice(voice_id) or self.store.create_voice(voice_id, display_name, traits)
        clip_generation_id = str(command.payload.get("clip_generation_id") or "").strip()
        clip_generation = self.store.get_generation(clip_generation_id) if clip_generation_id else None
        if clip_generation_id and not clip_generation:
            raise ValueError("clip_generation_id not found")
        profile = self.store.create_voice_profile(
            {
                "profile_id": profile_id,
                "voice_id": voice_id,
                "display_name": display_name,
                "description": command.payload.get("description"),
                "default_mode": default_mode,
                "clip_generation_id": clip_generation_id or None,
                "clip_audio_path": (clip_generation or {}).get("audio_path") or command.payload.get("clip_audio_path"),
                "clip_audio_sha256": (clip_generation or {}).get("audio_sha256") or command.payload.get("clip_audio_sha256"),
                "traits": traits,
                "request_hints": command.payload.get("request_hints") if isinstance(command.payload.get("request_hints"), dict) else {},
                "created_by": command.actor,
            }
        )
        event = self._event(command.command_id, "voice.profile.created", 1, {"voice_profile": profile})
        return {"ok": True, "voice": voice, "voice_profile": profile, "events": [event]}

    def _voice_profile_get(self, command: DramaCommand) -> dict[str, Any]:
        profile_id = str(command.payload.get("voice_profile_id") or command.payload.get("profile_id") or "").strip()
        if not profile_id:
            raise ValueError("payload.voice_profile_id is required")
        profile = self.store.get_voice_profile(profile_id)
        if not profile:
            raise ValueError("voice_profile_id not found")
        return {"ok": True, "voice_profile": profile, "events": []}

    def _voice_entangle(self, command: DramaCommand) -> dict[str, Any]:
        voice_id = str(command.payload.get("voice_id") or "").strip()
        if not voice_id:
            raise ValueError("payload.voice_id is required")
        xp_delta = int(command.payload.get("xp_delta") or 25)
        voice = self.store.entangle_voice(voice_id, xp_delta)
        event = self._event(command.command_id, "voice.entanglement.updated", 1, {"voice": voice})
        return {"ok": True, "voice": voice, "events": [event]}
