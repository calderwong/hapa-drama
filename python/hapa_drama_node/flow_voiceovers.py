from __future__ import annotations

import copy
import json
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

from .audio import inspect_wav
from .config import Settings, utc_now_iso
from .provenance import file_sha256


FLOW_VOICEOVER_VERSION = "0.1.0"
_SAFE_ID_RE = re.compile(r"[^a-zA-Z0-9_.-]+")
_ROUTE_OPTION_KEYS = (
    "voice_profile_id",
    "voice_id",
    "voice_clip_path",
    "use_default_voice",
    "dramabox_cfg_scale",
    "dramabox_stg_scale",
    "dramabox_stg_block",
    "dramabox_rescale_scale",
    "dramabox_steps",
    "dramabox_duration_multiplier",
    "dramabox_seed",
)

_NODE_LABELS = {
    "world-building-wiki": "Worldbuilding Wiki",
    "hapa-atlas": "Atlas",
    "hapa-node-space": "Node Space",
    "hapa-master-dashboard": "Master View",
    "hapa-lance-node": "Lance",
    "hapa-telemetry-node": "Telemetry",
    "hapa-library": "Library",
    "hapa-media-node": "Media node",
    "hapa-ltx-node": "LTX node",
    "hapa-open-tasks-node": "Open Tasks",
    "hapa-game-engine": "Game Engine",
    "hapa-anvil-node": "Anvil",
    "hapa-forge": "Forge",
    "hapa-song-registry": "Song Registry",
    "hapa-chat-app": "Chat",
    "hapa-agent-registry-node": "Agent Registry",
    "hapa-keys-node": "Keys",
    "hapa-crypto-node": "Crypto",
}


def safe_flow_id(value: Any, fallback: str = "flow") -> str:
    cleaned = _SAFE_ID_RE.sub("-", str(value or "").strip()).strip("-._").lower()
    return (cleaned or fallback)[:96]


def _flow_dir(settings: Settings, flow_id: str) -> Path:
    return settings.artifacts_dir / "flow_voiceovers" / safe_flow_id(flow_id)


def flow_voiceover_manifest_path(settings: Settings, flow_id: str) -> Path:
    return _flow_dir(settings, flow_id) / "manifest.json"


def read_flow_voiceover_manifest(settings: Settings, flow_id: str) -> dict[str, Any] | None:
    path = flow_voiceover_manifest_path(settings, flow_id)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def write_flow_voiceover_manifest(settings: Settings, manifest: dict[str, Any]) -> dict[str, Any]:
    flow_id = safe_flow_id(manifest.get("flow_id"))
    path = flow_voiceover_manifest_path(settings, flow_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest["flow_id"] = flow_id
    manifest["updated_at"] = utc_now_iso()
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def flow_voiceover_audio_path(settings: Settings, flow_id: str, step_key: str) -> Path:
    return _flow_dir(settings, flow_id) / f"{safe_flow_id(step_key, 'step')}.wav"


def _as_paragraphs(value: Any) -> list[str]:
    if isinstance(value, list):
        return [" ".join(str(item).split()) for item in value if str(item or "").strip()]
    if isinstance(value, str) and value.strip():
        return [" ".join(part.split()) for part in re.split(r"\n\s*\n", value.strip()) if part.strip()]
    return []


def _node_label(node_id: Any) -> str:
    value = str(node_id or "").strip()
    if not value:
        return "Unknown node"
    if value in _NODE_LABELS:
        return _NODE_LABELS[value]
    text = value
    if text.startswith("hapa-"):
        text = text[5:]
    if text.endswith("-node"):
        text = text[:-5]
    return " ".join(part.capitalize() for part in text.replace("_", "-").split("-") if part)


def _compact_script(text: str, max_chars: int = 260) -> str:
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= max_chars:
        return cleaned
    clipped = cleaned[:max_chars].rsplit(" ", 1)[0].rstrip(" ,;:")
    sentence_end = max(clipped.rfind("."), clipped.rfind("!"), clipped.rfind("?"))
    if sentence_end > max_chars * 0.55:
        clipped = clipped[: sentence_end + 1]
    return clipped.rstrip(".") + "."


def _word_count(text: str) -> int:
    return len([word for word in str(text or "").split() if word.strip()])


def _target_duration_seconds(text: str) -> float:
    # DramaBox MLX responds better with a bounded generation window. This keeps
    # flow narration short enough to feel attached to each packet animation.
    return round(min(12.0, max(8.0, (_word_count(text) / 2.0) + 1.0)), 2)


def _step_key(index: int, step: dict[str, Any]) -> str:
    if str(step.get("step_key") or step.get("id") or "").strip():
        return safe_flow_id(step.get("step_key") or step.get("id"), f"step-{index + 1:02d}")
    source = safe_flow_id(step.get("source"), "source")
    target = safe_flow_id(step.get("target"), "target")
    layer = safe_flow_id(step.get("layer") or "DATA", "data")
    return safe_flow_id(f"step-{index + 1:02d}-{source}-to-{target}-{layer}", f"step-{index + 1:02d}")


def build_spoken_script(flow: dict[str, Any], step: dict[str, Any], index: int, total: int) -> str:
    source = _node_label(step.get("source"))
    target = _node_label(step.get("target"))
    layer = str(step.get("layer") or "DATA").strip().upper()
    article = "an" if layer[:1] in {"A", "E", "I", "O"} else "a"
    label = " ".join(str(step.get("label") or "Flow handoff.").split())
    paragraphs = (
        _as_paragraphs(step.get("voiceover_script"))
        or _as_paragraphs(step.get("narrative"))
        or _as_paragraphs(step.get("explanation"))
    )
    if paragraphs:
        body = " ".join(paragraphs[:1])
    else:
        body = (
            f"{source} sends {article} {layer} handoff to {target}. "
            f"{label}"
        )
    return _compact_script(body)


def build_dramabox_prompt(spoken_script: str) -> str:
    dialogue = str(spoken_script or "").replace('"', "'")
    return f'A calm narrator says, "{dialogue}"'


def build_flow_voiceover_manifest(settings: Settings, request_data: dict[str, Any], *, base_url: str | None = None) -> dict[str, Any]:
    flow = request_data.get("flow") if isinstance(request_data.get("flow"), dict) else {}
    flow_id = safe_flow_id(request_data.get("flow_id") or request_data.get("id") or flow.get("id") or flow.get("name"))
    flow = {
        **flow,
        "id": flow_id,
        "name": request_data.get("flow_name") or request_data.get("name") or flow.get("name") or flow_id,
        "summary": request_data.get("summary") or flow.get("summary") or "",
    }
    steps = request_data.get("steps") if isinstance(request_data.get("steps"), list) else flow.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("flow voiceover queue requires at least one step")

    existing = read_flow_voiceover_manifest(settings, flow_id) or {}
    existing_items = {
        str(item.get("step_key") or ""): item
        for item in existing.get("items", [])
        if isinstance(item, dict) and str(item.get("step_key") or "").strip()
    }
    force = bool(request_data.get("force"))
    route = {
        "mode": str(request_data.get("mode") or "drama").strip().lower() or "drama",
        "tts_engine": str(request_data.get("tts_engine") or request_data.get("engine") or "dramabox").strip().lower() or "dramabox",
    }
    for key in _ROUTE_OPTION_KEYS:
        if key in request_data:
            route[key] = request_data.get(key)
    items: list[dict[str, Any]] = []
    total = len(steps)
    for index, raw_step in enumerate(steps):
        step = raw_step if isinstance(raw_step, dict) else {}
        key = _step_key(index, step)
        spoken_script = build_spoken_script(flow, step, index, total)
        prior = existing_items.get(key)
        if prior and prior.get("status") == "succeeded" and prior.get("audio_path") and Path(str(prior["audio_path"])).is_file() and not force:
            item = {**prior}
            item["spoken_script"] = spoken_script
            item["dramabox_prompt"] = build_dramabox_prompt(spoken_script)
            item["target_duration_seconds"] = prior.get("target_duration_seconds") or _target_duration_seconds(spoken_script)
        else:
            item = {
                "step_key": key,
                "index": index,
                "status": "queued",
                "source": step.get("source"),
                "target": step.get("target"),
                "layer": str(step.get("layer") or "DATA").strip().upper() or "DATA",
                "label": step.get("label") or "Flow handoff.",
                "spoken_script": spoken_script,
                "dramabox_prompt": build_dramabox_prompt(spoken_script),
                "target_duration_seconds": _target_duration_seconds(spoken_script),
                "created_at": utc_now_iso(),
            }
        items.append(item)

    manifest = {
        "version": FLOW_VOICEOVER_VERSION,
        "queue_id": existing.get("queue_id") or f"flow-voiceover-{flow_id}",
        "flow_id": flow_id,
        "flow_name": flow["name"],
        "summary": flow.get("summary") or "",
        "status": "queued",
        "route": route,
        "prompt_contract": {
            "engine": "dramabox",
            "spoken_text_only": True,
            "speaker": "A calm narrator",
            "style": "simple, steady, clean diction",
        },
        "items": items,
        "created_at": existing.get("created_at") or utc_now_iso(),
        "updated_at": utc_now_iso(),
    }
    _refresh_manifest_status(manifest)
    write_flow_voiceover_manifest(settings, manifest)
    return with_public_urls(manifest, base_url) if base_url else manifest


def _refresh_manifest_status(manifest: dict[str, Any]) -> None:
    items = [item for item in manifest.get("items", []) if isinstance(item, dict)]
    if not items:
        manifest["status"] = "empty"
        return
    statuses = {str(item.get("status") or "queued") for item in items}
    if statuses == {"succeeded"}:
        manifest["status"] = "succeeded"
    elif "running" in statuses:
        manifest["status"] = "running"
    elif "failed" in statuses and len(statuses) == 1:
        manifest["status"] = "failed"
    elif "failed" in statuses:
        manifest["status"] = "partial_failed"
    elif "queued" in statuses:
        manifest["status"] = "queued"
    else:
        manifest["status"] = "unknown"


def with_public_urls(manifest: dict[str, Any], base_url: str | None) -> dict[str, Any]:
    out = copy.deepcopy(manifest)
    if not base_url:
        return out
    base = str(base_url).rstrip("/")
    flow_id = safe_flow_id(out.get("flow_id"))
    out["manifest_url"] = f"{base}/v1/flow-voiceovers/{flow_id}/manifest"
    for item in out.get("items", []):
        if not isinstance(item, dict):
            continue
        step_key = safe_flow_id(item.get("step_key"), "step")
        item["audio_url"] = f"{base}/v1/flow-voiceovers/{flow_id}/steps/{step_key}/audio" if item.get("status") == "succeeded" else None
    return out


def process_flow_voiceover_queue(
    settings: Settings,
    router: Any,
    manifest: dict[str, Any],
    *,
    force: bool = False,
    base_url: str | None = None,
) -> dict[str, Any]:
    route = manifest.get("route") if isinstance(manifest.get("route"), dict) else {}
    flow_id = safe_flow_id(manifest.get("flow_id"))
    manifest["status"] = "running"
    write_flow_voiceover_manifest(settings, manifest)

    for item in manifest.get("items", []):
        if not isinstance(item, dict):
            continue
        step_key = safe_flow_id(item.get("step_key"), "step")
        audio_path = flow_voiceover_audio_path(settings, flow_id, step_key)
        if (
            not force
            and item.get("status") == "succeeded"
            and audio_path.is_file()
            and item.get("audio_sha256")
        ):
            continue

        item["status"] = "running"
        item["error"] = None
        item["started_at"] = utc_now_iso()
        _refresh_manifest_status(manifest)
        write_flow_voiceover_manifest(settings, manifest)
        payload = {
            "text": item["spoken_script"],
            "tts_engine": route.get("tts_engine") or "dramabox",
            "dramabox_prompt": item.get("dramabox_prompt"),
            "dramabox_speaker": "A calm narrator",
            "dramabox_style": "speaks simply with steady pacing and clean diction",
            "dramabox_gen_duration_seconds": item.get("target_duration_seconds"),
            "emotion": {"style": "cinematic operator narration", "intensity": 0.62},
            "timing": {"target_duration_seconds": item.get("target_duration_seconds")},
            "output": {"format": "wav", "mint_card": False, "cymatica_bundle": False},
        }
        for key in _ROUTE_OPTION_KEYS:
            if key in route and route.get(key) not in (None, ""):
                payload[key] = route[key]
        command = {
            "api_version": "v1",
            "command_id": f"flow-voiceover-{flow_id}-{step_key}-{uuid.uuid4().hex[:8]}",
            "actor": "node:hapa-drama-flow-voiceover-queue",
            "kind": "synthesize",
            "mode": route.get("mode") if route.get("mode") in {"auto", "drama", "flow", "ultrafast"} else "drama",
            "payload": payload,
            "provenance": {
                "source_node": "hapa-drama",
                "surface": "flow_voiceover_queue",
                "flow_id": flow_id,
                "step_key": step_key,
            },
            "options": {},
        }
        try:
            result = router.dispatch(command)
            generation = result.get("generation") if isinstance(result, dict) else {}
            source_audio = Path(str(generation.get("audio_path") or "")).expanduser().resolve()
            if not source_audio.is_file():
                raise RuntimeError("generation completed without a readable audio path")
            audio_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_audio, audio_path)
            inspection = inspect_wav(audio_path)
            item.update(
                {
                    "status": "succeeded",
                    "generation_id": generation.get("generation_id"),
                    "engine": generation.get("engine"),
                    "mode": generation.get("mode"),
                    "audio_path": str(audio_path),
                    "audio_sha256": file_sha256(audio_path),
                    "duration_seconds": inspection.duration_seconds,
                    "sample_rate": inspection.sample_rate,
                    "completed_at": utc_now_iso(),
                }
            )
        except Exception as exc:
            item.update({"status": "failed", "error": str(exc), "completed_at": utc_now_iso()})
        _refresh_manifest_status(manifest)
        write_flow_voiceover_manifest(settings, manifest)

    _refresh_manifest_status(manifest)
    write_flow_voiceover_manifest(settings, manifest)
    return with_public_urls(manifest, base_url) if base_url else manifest


def flow_voiceover_queue_counts(settings: Settings) -> dict[str, int]:
    root = settings.artifacts_dir / "flow_voiceovers"
    counts = {"flows": 0, "queued": 0, "running": 0, "succeeded": 0, "failed": 0}
    if not root.is_dir():
        return counts
    for path in root.glob("*/manifest.json"):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        counts["flows"] += 1
        for item in manifest.get("items", []):
            if not isinstance(item, dict):
                continue
            status = str(item.get("status") or "queued")
            if status in counts:
                counts[status] += 1
    return counts
