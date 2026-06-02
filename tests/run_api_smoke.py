from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
import uuid
from contextlib import nullcontext
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PYTHON_DIR = ROOT / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

from hapa_drama_node.audio import inspect_wav
from hapa_drama_node.cymatica import validate_cymatica_bundle, validate_cymatica_handoff


def repo_root() -> Path:
    return ROOT


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def http_json(method: str, url: str, token: str | None = None, payload: dict[str, Any] | None = None, timeout: float = 5.0) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as res:
        raw = res.read()
    return json.loads(raw.decode("utf-8")) if raw else {}


def http_bytes(method: str, url: str, token: str | None = None, timeout: float = 5.0) -> bytes:
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return res.read()


def wait_for_health(base_url: str, process: subprocess.Popen[bytes], timeout_seconds: float, log_path: Path) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_error = ""
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"server exited early with code {process.returncode}; log={log_path.read_text(encoding='utf-8', errors='replace')}")
        try:
            health = http_json("GET", base_url + "/health", timeout=1.0)
            if health.get("ok") is True:
                return health
        except Exception as exc:
            last_error = str(exc)
            time.sleep(0.2)
    raise RuntimeError(f"server did not become healthy: {last_error}")


def main() -> int:
    root = repo_root()
    out_dir = root / "artifacts" / "self_test"
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "hapa_drama_api_smoke_latest.json"
    log_path = out_dir / "hapa_drama_api_smoke_server.log"
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    token = "hapa-drama-api-smoke-token"
    run_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    run_dir = out_dir / "api_smoke_runtime" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    with nullcontext(str(run_dir)) as raw_tmp:
        tmp = Path(raw_tmp)
        env = os.environ.copy()
        python_path = str(root / "python")
        if env.get("PYTHONPATH"):
            python_path = python_path + os.pathsep + str(env["PYTHONPATH"])
        env.update(
            {
                "PYTHONPATH": python_path,
                "HAPA_DRAMA_TOKEN": token,
                "HAPA_DRAMA_TOKEN_FILE": str(tmp / ".node_token"),
                "HAPA_DRAMA_STORAGE_DIR": str(tmp / "data"),
                "HAPA_DRAMA_ARTIFACTS_DIR": str(tmp / "artifacts"),
                "HAPA_DRAMA_RUNTIME_FILE": str(tmp / "runtime" / "hapa_drama_runtime.json"),
                "HAPA_DRAMA_PORT": str(port),
                "HAPA_DRAMA_HOST": "127.0.0.1",
            }
        )
        with log_path.open("wb") as log_file:
            process = subprocess.Popen(
                [sys.executable, "-m", "hapa_drama_node.cli", "serve", "--host", "127.0.0.1", "--port", str(port)],
                cwd=str(root),
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )
        try:
            started_at = time.monotonic()
            health = wait_for_health(base_url, process, 15.0, log_path)
            local_session = http_json("GET", base_url + "/local/session")
            capabilities = http_json("GET", base_url + "/capabilities", token=token)
            command = {
                "api_version": "v1",
                "command_id": "api-smoke-1",
                "actor": "api-smoke:hapa-drama",
                "kind": "synthesize",
                "mode": "flow",
                "payload": {
                    "text": "Hapa Drama live API smoke.",
                    "output": {"format": "wav", "mint_card": True, "cymatica_bundle": True},
                },
                "provenance": {"source_node": "hapa-drama", "surface": "api-smoke"},
                "options": {},
            }
            synth = http_json("POST", base_url + "/v1/commands", token=token, payload=command, timeout=10.0)
            generation = synth.get("generation") or {}
            synth_process = synth.get("process") or {}
            generation_id = str(generation.get("generation_id") or "")
            generation_process = http_json("GET", base_url + f"/v1/generations/{generation_id}/process", token=token).get("process") or {}
            profile_command = {
                "api_version": "v1",
                "command_id": "api-smoke-profile-1",
                "actor": "api-smoke:hapa-drama",
                "kind": "voice.profile.create",
                "mode": "auto",
                "payload": {
                    "profile_id": "profile-api-smoke",
                    "voice_id": "voice-api-smoke",
                    "display_name": "API Smoke Voice",
                    "default_mode": "drama",
                    "clip_generation_id": generation_id,
                    "traits": {"tone": "smoke"},
                    "request_hints": {"requested_by": "api-smoke"},
                },
                "provenance": {"source_node": "hapa-drama", "surface": "api-smoke"},
                "options": {},
            }
            profile_create = http_json("POST", base_url + "/v1/commands", token=token, payload=profile_command, timeout=10.0)
            profile_list = http_json("GET", base_url + "/v1/voice-profiles", token=token)
            profile_get = http_json("GET", base_url + "/v1/voice-profiles/profile-api-smoke", token=token)
            profile_clip = http_bytes("GET", base_url + "/v1/voice-profiles/profile-api-smoke/clip", token=token)
            profile_synth_command = {
                "api_version": "v1",
                "command_id": "api-smoke-profile-synth-1",
                "actor": "node:api-smoke-agent",
                "kind": "synthesize",
                "mode": "auto",
                "payload": {
                    "text": "A Hapa node is requesting the smoke voice profile.",
                    "voice_profile_id": "profile-api-smoke",
                    "request": {"requested_by": "node:api-smoke-agent"},
                    "output": {"format": "wav", "mint_card": True, "cymatica_bundle": True},
                },
                "provenance": {"source_node": "node:api-smoke-agent", "surface": "api-smoke"},
                "options": {},
            }
            profile_synth = http_json("POST", base_url + "/v1/commands", token=token, payload=profile_synth_command, timeout=10.0)
            profile_generation = profile_synth.get("generation") or {}
            telemetry = http_json("GET", base_url + "/v1/telemetry", token=token)
            audio_path = Path(str(generation.get("audio_path") or ""))
            bundle_path = Path(str(generation.get("cymatica_bundle_path") or ""))
            handoff_path = Path(str(generation.get("cymatica_handoff_path") or ""))
            handoff_zip_path = Path(str(generation.get("cymatica_handoff_zip_path") or ""))
            downloaded_audio = http_bytes("GET", base_url + f"/v1/generations/{generation_id}/audio", token=token)
            downloaded_card = http_json("GET", base_url + f"/v1/generations/{generation_id}/card", token=token)
            downloaded_manifest = http_json("GET", base_url + f"/v1/generations/{generation_id}/cymatica-manifest", token=token)
            downloaded_handoff = http_bytes("GET", base_url + f"/v1/generations/{generation_id}/cymatica-handoff", token=token)
            audio_inspection = inspect_wav(audio_path)
            cymatica_validation = validate_cymatica_bundle(bundle_path)
            handoff_validation = validate_cymatica_handoff(handoff_path)
            handoff_zip_validation = validate_cymatica_handoff(handoff_zip_path)
            checks = [
                {"name": "health", "ok": health.get("ok") is True},
                {"name": "local_session_token", "ok": local_session.get("token") == token and local_session.get("loopback_only") is True},
                {"name": "capabilities", "ok": capabilities.get("feature_id") == "hapa.voice.synthesis"},
                {"name": "capabilities_profile_requests", "ok": "hapa.voice.profile_requests" in capabilities.get("capability_ids", [])},
                {"name": "capabilities_process_state", "ok": "hapa.telemetry.process_state" in capabilities.get("capability_ids", [])},
                {"name": "synthesize", "ok": synth.get("ok") is True and generation.get("status") == "succeeded"},
                {"name": "synthesize_audible_wav", "ok": audio_inspection.duration_seconds >= 0.25 and audio_inspection.normalized_rms >= 0.0005, "duration_seconds": audio_inspection.duration_seconds, "normalized_rms": audio_inspection.normalized_rms},
                {"name": "synthesize_process_response", "ok": synth_process.get("generation_id") == generation_id and synth_process.get("status") == "succeeded" and synth_process.get("progress") == 1.0},
                {"name": "generation_process_endpoint", "ok": generation_process.get("generation_id") == generation_id and generation_process.get("stage") == "completed" and len(generation_process.get("timeline", [])) >= 4},
                {"name": "telemetry_recent_processes", "ok": telemetry.get("node_id") == "hapa-drama" and any(item.get("generation_id") == generation_id for item in telemetry.get("recent_processes", []))},
                {"name": "voice_profile_create", "ok": profile_create.get("voice_profile", {}).get("profile_id") == "profile-api-smoke"},
                {"name": "voice_profile_list", "ok": any(item.get("profile_id") == "profile-api-smoke" for item in profile_list.get("voice_profiles", []))},
                {"name": "voice_profile_get", "ok": profile_get.get("voice_profile", {}).get("voice_id") == "voice-api-smoke"},
                {"name": "voice_profile_clip_download", "ok": profile_clip.startswith(b"RIFF") and len(profile_clip) > 44, "bytes": len(profile_clip)},
                {"name": "profile_synthesize", "ok": profile_synth.get("ok") is True and profile_generation.get("voice_profile_id") == "profile-api-smoke" and profile_generation.get("mode") == "drama"},
                {"name": "audio_exists", "ok": audio_path.exists(), "path": str(audio_path)},
                {"name": "cymatica_bundle_exists", "ok": bundle_path.exists(), "path": str(bundle_path)},
                {"name": "cymatica_handoff_exists", "ok": handoff_path.exists(), "path": str(handoff_path)},
                {"name": "cymatica_handoff_zip_exists", "ok": handoff_zip_path.exists(), "path": str(handoff_zip_path)},
                {"name": "audio_download", "ok": downloaded_audio.startswith(b"RIFF") and len(downloaded_audio) > 44, "bytes": len(downloaded_audio)},
                {"name": "card_download", "ok": downloaded_card.get("id") == generation.get("card_id")},
                {"name": "cymatica_manifest_download", "ok": downloaded_manifest.get("generation_id") == generation_id},
                {"name": "cymatica_bundle_validation", "ok": cymatica_validation.get("ok") is True, "stem_count": cymatica_validation.get("stem_count")},
                {"name": "cymatica_handoff_download", "ok": downloaded_handoff.startswith(b"PK") and len(downloaded_handoff) > 100, "bytes": len(downloaded_handoff)},
                {"name": "cymatica_handoff_validation", "ok": handoff_validation.get("ok") is True, "stem_count": handoff_validation.get("stem_count")},
                {"name": "cymatica_handoff_zip_validation", "ok": handoff_zip_validation.get("ok") is True, "stem_count": handoff_zip_validation.get("stem_count")},
            ]
            report = {
                "ok": all(bool(check.get("ok")) for check in checks),
                "base_url": base_url,
                "elapsed_seconds": round(time.monotonic() - started_at, 3),
                "checks": checks,
                "generation_id": generation_id,
                "log_path": str(log_path),
                "artifact_root": str(tmp / "artifacts"),
                "profile_generation_id": profile_generation.get("generation_id"),
                "cymatica_validation": cymatica_validation,
                "cymatica_handoff_validation": handoff_validation,
                "cymatica_handoff_zip_validation": handoff_zip_validation,
            }
            report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(report, indent=2))
            return 0 if report["ok"] else 1
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
