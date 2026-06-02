from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from .audio import inspect_wav
from .config import load_settings
from .cymatica import validate_cymatica_bundle, validate_cymatica_handoff


_ROOT_DIR = Path(__file__).resolve().parents[2]


def _default_base_url() -> str:
    env_url = str(os.environ.get("HAPA_DRAMA_BASE_URL") or "").strip()
    if env_url:
        return env_url
    runtime = _runtime_payload()
    return str(runtime.get("base_url") or "http://127.0.0.1:8758").strip()


def _runtime_payload() -> dict[str, Any]:
    runtime_file = Path(os.environ.get("HAPA_DRAMA_RUNTIME_FILE") or "artifacts/runtime/hapa_drama_runtime.json").expanduser()
    if not runtime_file.exists():
        return {}
    try:
        payload = json.loads(runtime_file.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def resolve_token(raw: str | None = None) -> str:
    if raw and raw.strip():
        return raw.strip()
    env_token = str(os.environ.get("HAPA_DRAMA_TOKEN") or "").strip()
    if env_token:
        return env_token
    token_file = Path(os.environ.get("HAPA_DRAMA_TOKEN_FILE") or ".node_token").expanduser()
    if token_file.exists():
        return token_file.read_text(encoding="utf-8").strip()
    runtime_token_path = str(_runtime_payload().get("token_path") or "").strip()
    if runtime_token_path:
        runtime_token_file = Path(runtime_token_path).expanduser()
        if runtime_token_file.exists():
            return runtime_token_file.read_text(encoding="utf-8").strip()
    return ""


def _parse_json_object(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise RuntimeError("JSON value must be an object")
    return value


def _http_json(method: str, url: str, *, token: str | None = None, payload: dict[str, Any] | None = None, timeout: float = 60.0) -> dict[str, Any]:
    body = None
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url=url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            raw = res.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else ""
        raise RuntimeError(f"HTTP {exc.code}: {text}")


def _http_bytes(method: str, url: str, *, token: str | None = None, timeout: float = 60.0) -> bytes:
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url=url, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return res.read()
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else ""
        raise RuntimeError(f"HTTP {exc.code}: {text}")


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    settings = load_settings()
    host = str(args.host or settings.host)
    port = int(args.port or settings.port)
    os.environ["HAPA_DRAMA_HOST"] = host
    os.environ["HAPA_DRAMA_PORT"] = str(port)
    uvicorn.run("hapa_drama_node.app:app", host=host, port=port, reload=bool(args.reload))
    return 0


def cmd_health(args: argparse.Namespace) -> int:
    data = _http_json("GET", str(args.base_url).rstrip("/") + "/health")
    print(json.dumps(data, indent=2))
    return 0


def cmd_capabilities(args: argparse.Namespace) -> int:
    token = resolve_token(args.token)
    if not token:
        raise RuntimeError("Token required")
    data = _http_json("GET", str(args.base_url).rstrip("/") + "/capabilities", token=token)
    print(json.dumps(data, indent=2))
    return 0


def cmd_docs(args: argparse.Namespace) -> int:
    if getattr(args, "from_api", False):
        data = _http_json("GET", str(args.base_url).rstrip("/") + "/docs/readme", timeout=float(args.timeout_seconds))
        if getattr(args, "json", False):
            print(json.dumps(data, indent=2))
        else:
            print(data.get("content") or "")
        return 0 if data.get("ok") else 1
    readme = _ROOT_DIR / "README.md"
    if not readme.is_file():
        raise RuntimeError(f"README.md not found at {readme}")
    content = readme.read_text(encoding="utf-8")
    if getattr(args, "json", False):
        print(json.dumps({"ok": True, "document_id": "README.md", "source_path": str(readme), "content": content}, indent=2))
    else:
        print(content)
    return 0


def build_synthesize_command(args: argparse.Namespace) -> dict[str, Any]:
    text = str(args.text or "").strip()
    if args.script:
        text = Path(args.script).expanduser().read_text(encoding="utf-8")
    payload = {
        "text": text,
        "voice_id": args.voice_id,
        "voice_profile_id": getattr(args, "voice_profile_id", None),
        "emotion": {"style": args.emotion_style, "intensity": float(args.emotion_intensity)},
        "timing": {"bpm": args.bpm, "start_seconds": args.start_seconds, "target_duration_seconds": args.target_duration_seconds},
        "output": {"format": "wav", "mint_card": not args.no_card, "cymatica_bundle": not args.no_cymatica},
    }
    tts_engine = str(getattr(args, "tts_engine", "") or "").strip()
    if tts_engine:
        payload["tts_engine"] = tts_engine
    voice_clip_path = str(getattr(args, "voice_clip_path", "") or "").strip()
    if voice_clip_path:
        payload["voice_clip_path"] = voice_clip_path
    chatterbox_model = str(getattr(args, "chatterbox_model", "") or "").strip()
    if chatterbox_model:
        payload["chatterbox_model"] = chatterbox_model
    macos_voice = str(getattr(args, "macos_voice", "") or "").strip()
    if macos_voice:
        payload["macos_voice"] = macos_voice
    requester_node = str(getattr(args, "requester_node", "") or "").strip()
    if requester_node:
        payload["request"] = {"requested_by": requester_node}
    return {
        "api_version": "v1",
        "command_id": args.command_id or str(uuid.uuid4()),
        "actor": args.actor or "cli:hapa-drama",
        "kind": "synthesize",
        "mode": args.mode,
        "payload": payload,
        "provenance": {"source_node": "hapa-drama", "surface": "cli"},
        "options": {"async": False},
    }


def cmd_synthesize(args: argparse.Namespace) -> int:
    token = resolve_token(args.token)
    if not token:
        raise RuntimeError("Token required")
    base = str(args.base_url).rstrip("/")
    command = build_synthesize_command(args)
    data = _http_json("POST", base + "/v1/commands", token=token, payload=command, timeout=float(args.timeout_seconds))
    save_audio = str(getattr(args, "save_audio", "") or "").strip()
    generation = data.get("generation") if isinstance(data, dict) else None
    if save_audio and isinstance(generation, dict) and generation.get("generation_id"):
        out_path = Path(save_audio).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        audio_path = Path(str(generation.get("audio_path") or ""))
        if audio_path.is_file():
            shutil.copyfile(audio_path, out_path)
        else:
            raw = _http_bytes("GET", base + f"/v1/generations/{generation['generation_id']}/audio", token=token, timeout=float(args.timeout_seconds))
            out_path.write_bytes(raw)
        data["saved_audio_path"] = str(out_path.resolve())
    print(json.dumps(data, indent=2))
    return 0 if data.get("ok") else 1


def cmd_voice_create(args: argparse.Namespace) -> int:
    token = resolve_token(args.token)
    if not token:
        raise RuntimeError("Token required")
    command = {
        "api_version": "v1",
        "command_id": str(uuid.uuid4()),
        "actor": args.actor or "cli:hapa-drama",
        "kind": "voice.create",
        "mode": "auto",
        "payload": {"display_name": args.name, "voice_id": args.voice_id, "traits": {}},
        "provenance": {"source_node": "hapa-drama", "surface": "cli"},
        "options": {},
    }
    data = _http_json("POST", str(args.base_url).rstrip("/") + "/v1/commands", token=token, payload=command)
    print(json.dumps(data, indent=2))
    return 0 if data.get("ok") else 1


def cmd_voice_profile_create(args: argparse.Namespace) -> int:
    token = resolve_token(args.token)
    if not token:
        raise RuntimeError("Token required")
    command = {
        "api_version": "v1",
        "command_id": str(uuid.uuid4()),
        "actor": args.actor or "cli:hapa-drama",
        "kind": "voice.profile.create",
        "mode": "auto",
        "payload": {
            "profile_id": args.profile_id,
            "voice_id": args.voice_id,
            "display_name": args.name,
            "description": args.description,
            "default_mode": args.default_mode,
            "clip_generation_id": args.clip_generation_id,
            "traits": _parse_json_object(args.traits_json),
            "request_hints": _parse_json_object(args.hints_json),
        },
        "provenance": {"source_node": "hapa-drama", "surface": "cli"},
        "options": {},
    }
    data = _http_json("POST", str(args.base_url).rstrip("/") + "/v1/commands", token=token, payload=command)
    print(json.dumps(data, indent=2))
    return 0 if data.get("ok") else 1


def cmd_voice_profiles(args: argparse.Namespace) -> int:
    token = resolve_token(args.token)
    if not token:
        raise RuntimeError("Token required")
    data = _http_json("GET", str(args.base_url).rstrip("/") + "/v1/voice-profiles", token=token)
    print(json.dumps(data, indent=2))
    return 0


def cmd_voice_profile_get(args: argparse.Namespace) -> int:
    token = resolve_token(args.token)
    if not token:
        raise RuntimeError("Token required")
    data = _http_json("GET", str(args.base_url).rstrip("/") + f"/v1/voice-profiles/{args.profile_id}", token=token)
    print(json.dumps(data, indent=2))
    return 0


def cmd_voices(args: argparse.Namespace) -> int:
    token = resolve_token(args.token)
    if not token:
        raise RuntimeError("Token required")
    data = _http_json("GET", str(args.base_url).rstrip("/") + "/v1/voices", token=token)
    print(json.dumps(data, indent=2))
    return 0


def cmd_self_test(args: argparse.Namespace) -> int:
    token = resolve_token(args.token)
    if not token:
        raise RuntimeError("Token required")
    base = str(args.base_url).rstrip("/")
    report: dict[str, Any] = {"ok": False, "checks": []}
    health = _http_json("GET", base + "/health")
    report["checks"].append({"name": "health", "ok": bool(health.get("ok"))})
    caps = _http_json("GET", base + "/capabilities", token=token)
    report["checks"].append({"name": "capabilities", "ok": caps.get("feature_id") == "hapa.voice.synthesis"})
    cmd = {
        "api_version": "v1",
        "command_id": str(uuid.uuid4()),
        "actor": "self-test:hapa-drama",
        "kind": "synthesize",
        "mode": "flow",
        "payload": {"text": "Hapa Drama self test.", "output": {"mint_card": True, "cymatica_bundle": True}},
        "provenance": {"source_node": "hapa-drama", "surface": "self-test"},
        "options": {},
    }
    synth = _http_json("POST", base + "/v1/commands", token=token, payload=cmd)
    generation = synth.get("generation") or {}
    audio_path = Path(str(generation.get("audio_path") or ""))
    audio_ok = False
    audio_detail: dict[str, Any] = {}
    if audio_path.exists():
        inspection = inspect_wav(audio_path)
        audio_ok = inspection.duration_seconds >= 0.25 and inspection.normalized_rms >= 0.0005
        audio_detail = {
            "duration_seconds": round(inspection.duration_seconds, 3),
            "normalized_rms": round(inspection.normalized_rms, 6),
            "sample_rate": inspection.sample_rate,
        }
    report["checks"].append(
        {
            "name": "synthesize_audio",
            "ok": bool(synth.get("ok") and audio_path.exists() and audio_ok),
            "audio_path": str(audio_path),
            "engine": generation.get("engine"),
            **audio_detail,
        }
    )
    report["ok"] = all(bool(c.get("ok")) for c in report["checks"])
    out_dir = Path("artifacts/self_test")
    out_dir.mkdir(parents=True, exist_ok=True)
    latest = out_dir / "hapa_drama_self_test_latest.json"
    latest.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


def cmd_cymatica_validate(args: argparse.Namespace) -> int:
    report = validate_cymatica_bundle(args.bundle_path)
    print(json.dumps(report, indent=2))
    return 0 if report.get("ok") else 1


def cmd_cymatica_handoff_validate(args: argparse.Namespace) -> int:
    report = validate_cymatica_handoff(args.path)
    print(json.dumps(report, indent=2))
    return 0 if report.get("ok") else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hapa-drama")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.add_argument("--reload", action="store_true")
    serve.set_defaults(func=cmd_serve)
    health = sub.add_parser("health")
    health.add_argument("--base-url", default=_default_base_url())
    health.set_defaults(func=cmd_health)
    caps = sub.add_parser("capabilities")
    caps.add_argument("--base-url", default=_default_base_url())
    caps.add_argument("--token")
    caps.set_defaults(func=cmd_capabilities)
    docs = sub.add_parser("docs")
    docs.add_argument("--base-url", default=_default_base_url())
    docs.add_argument("--from-api", action="store_true", help="Fetch README through GET /docs/readme instead of reading the local file")
    docs.add_argument("--json", action="store_true", help="Print the docs payload as JSON")
    docs.add_argument("--timeout-seconds", type=float, default=10.0)
    docs.set_defaults(func=cmd_docs)
    syn = sub.add_parser("synthesize")
    syn.add_argument("--base-url", default=_default_base_url())
    syn.add_argument("--token")
    syn.add_argument("--command-id")
    syn.add_argument("--actor")
    syn.add_argument("--mode", default="auto", choices=["auto", "drama", "flow", "ultrafast"])
    syn.add_argument("--text")
    syn.add_argument("--script")
    syn.add_argument("--voice-id")
    syn.add_argument("--voice-profile-id")
    syn.add_argument("--voice-clip-path", help="Reference clip path for engines that support cloning")
    syn.add_argument("--tts-engine", choices=["chatterbox", "dramabox", "dramabox-mlx", "dramabox-cuda", "mlx-audio", "macos-speech"], help="Force a specific synthesis backend")
    syn.add_argument("--chatterbox-model", choices=["standard", "turbo"], help="Use a Chatterbox model variant when --tts-engine=chatterbox")
    syn.add_argument("--macos-voice", help="Use a named macOS `say` voice when the macOS speech backend is selected")
    syn.add_argument("--requester-node")
    syn.add_argument("--emotion-style", default="neutral")
    syn.add_argument("--emotion-intensity", type=float, default=0.0)
    syn.add_argument("--bpm", type=float)
    syn.add_argument("--start-seconds", type=float, default=0.0)
    syn.add_argument("--target-duration-seconds", type=float)
    syn.add_argument("--no-card", action="store_true")
    syn.add_argument("--no-cymatica", action="store_true")
    syn.add_argument("--save-audio", help="Copy or download the generated WAV to this path")
    syn.add_argument("--timeout-seconds", type=float, default=60.0)
    syn.set_defaults(func=cmd_synthesize)
    vc = sub.add_parser("voice-create")
    vc.add_argument("--base-url", default=_default_base_url())
    vc.add_argument("--token")
    vc.add_argument("--actor")
    vc.add_argument("--voice-id")
    vc.add_argument("--name", required=True)
    vc.set_defaults(func=cmd_voice_create)
    vpc = sub.add_parser("voice-profile-create")
    vpc.add_argument("--base-url", default=_default_base_url())
    vpc.add_argument("--token")
    vpc.add_argument("--actor")
    vpc.add_argument("--profile-id")
    vpc.add_argument("--voice-id")
    vpc.add_argument("--name", required=True)
    vpc.add_argument("--description")
    vpc.add_argument("--default-mode", default="auto", choices=["auto", "drama", "flow", "ultrafast"])
    vpc.add_argument("--clip-generation-id")
    vpc.add_argument("--traits-json")
    vpc.add_argument("--hints-json")
    vpc.set_defaults(func=cmd_voice_profile_create)
    vps = sub.add_parser("voice-profiles")
    vps.add_argument("--base-url", default=_default_base_url())
    vps.add_argument("--token")
    vps.set_defaults(func=cmd_voice_profiles)
    vpg = sub.add_parser("voice-profile-get")
    vpg.add_argument("--base-url", default=_default_base_url())
    vpg.add_argument("--token")
    vpg.add_argument("--profile-id", required=True)
    vpg.set_defaults(func=cmd_voice_profile_get)
    voices = sub.add_parser("voices")
    voices.add_argument("--base-url", default=_default_base_url())
    voices.add_argument("--token")
    voices.set_defaults(func=cmd_voices)
    st = sub.add_parser("self-test")
    st.add_argument("--base-url", default=_default_base_url())
    st.add_argument("--token")
    st.set_defaults(func=cmd_self_test)
    cv = sub.add_parser("cymatica-validate")
    cv.add_argument("--bundle-path", required=True)
    cv.set_defaults(func=cmd_cymatica_validate)
    hv = sub.add_parser("cymatica-handoff-validate")
    hv.add_argument("--path", required=True)
    hv.set_defaults(func=cmd_cymatica_handoff_validate)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
