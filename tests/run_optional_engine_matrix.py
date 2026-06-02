from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PYTHON_DIR = ROOT / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

from hapa_drama_node.audio import assert_audible_wav, inspect_wav


DEFAULT_VOICE_CLIP = Path(os.environ.get("HAPA_DRAMA_TEST_VOICE_CLIP") or str(ROOT / "data" / "default_voice" / "operator-default-reference.wav"))
REFERENCE_TEXT = "This reference clip was provided by the operator as the source voice for Hapa Drama optional engine tests."
SCRIPT = "Hapa Drama optional engine test. This script should become a real spoken WAV from the selected backend."


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def http_json(method: str, url: str, *, token: str | None = None, payload: dict[str, Any] | None = None, timeout: float = 60.0) -> dict[str, Any]:
    headers: dict[str, str] = {}
    body = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            raw = res.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    return json.loads(raw.decode("utf-8")) if raw else {}


def run_command(command: list[str], *, timeout: float, env: dict[str, str] | None = None) -> dict[str, Any]:
    started = time.monotonic()
    try:
        completed = subprocess.run(command, check=True, capture_output=True, text=True, timeout=timeout, env=env)
        return {"ok": True, "elapsed_seconds": round(time.monotonic() - started, 3), "stdout_tail": completed.stdout[-2000:], "stderr_tail": completed.stderr[-2000:]}
    except subprocess.TimeoutExpired as exc:
        return {"ok": False, "elapsed_seconds": round(time.monotonic() - started, 3), "error": f"timeout after {timeout:.0f}s", "stdout_tail": str(exc.stdout or "")[-2000:], "stderr_tail": str(exc.stderr or "")[-2000:]}
    except subprocess.CalledProcessError as exc:
        return {"ok": False, "elapsed_seconds": round(time.monotonic() - started, 3), "error": f"exit code {exc.returncode}", "stdout_tail": exc.stdout[-2000:], "stderr_tail": exc.stderr[-2000:]}


def normalize_reference_audio(source: Path, out_dir: Path) -> dict[str, Any]:
    ref_path = out_dir / "reference" / "operator-voice-24k.wav"
    ref_path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return {"ok": False, "error": "ffmpeg not found", "path": str(ref_path)}
    result = run_command(
        [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(source), "-ac", "1", "-ar", "24000", "-t", "20", "-sample_fmt", "s16", str(ref_path)],
        timeout=45,
    )
    result["path"] = str(ref_path)
    if result.get("ok"):
        inspection = assert_audible_wav(ref_path, min_duration_seconds=5.0, min_normalized_rms=0.0005)
        result["inspection"] = {"duration_seconds": round(inspection.duration_seconds, 3), "sample_rate": inspection.sample_rate, "normalized_rms": round(inspection.normalized_rms, 6)}
    return result


def launch_server(case_name: str, out_dir: Path, env_overrides: dict[str, str]) -> tuple[subprocess.Popen[bytes], str, str, Path]:
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    token = f"hapa-optional-{uuid.uuid4().hex}"
    runtime_dir = out_dir / "runtime" / case_name
    log_path = out_dir / "logs" / f"{case_name}.log"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(PYTHON_DIR) + os.pathsep + env.get("PYTHONPATH", ""),
            "HAPA_DRAMA_TOKEN": token,
            "HAPA_DRAMA_TOKEN_FILE": str(runtime_dir / ".node_token"),
            "HAPA_DRAMA_STORAGE_DIR": str(runtime_dir / "data"),
            "HAPA_DRAMA_ARTIFACTS_DIR": str(runtime_dir / "artifacts"),
            "HAPA_DRAMA_RUNTIME_FILE": str(runtime_dir / "runtime" / "hapa_drama_runtime.json"),
            "HAPA_DRAMA_HOST": "127.0.0.1",
            "HAPA_DRAMA_PORT": str(port),
            "HAPA_DRAMA_ENABLE_MACOS_SPEECH": "1",
            "HAPA_DRAMA_STUB_SUCCESS": "1",
        }
    )
    env.update(env_overrides)
    with log_path.open("wb") as log_file:
        process = subprocess.Popen(
            [sys.executable, "-m", "hapa_drama_node.cli", "serve", "--host", "127.0.0.1", "--port", str(port)],
            cwd=str(ROOT),
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
    return process, base_url, token, log_path


def wait_for_health(base_url: str, process: subprocess.Popen[bytes], log_path: Path, timeout_seconds: float = 30.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_error = ""
    while time.monotonic() < deadline:
        if process.poll() is not None:
            log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
            raise RuntimeError(f"server exited early with code {process.returncode}; log={log[-4000:]}")
        try:
            health = http_json("GET", base_url + "/health", timeout=5.0)
            if health.get("ok") is True:
                return health
        except Exception as exc:
            last_error = str(exc)
        time.sleep(0.25)
    raise RuntimeError(f"server did not become healthy: {last_error}")


def stop_server(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def upload_profile(base_url: str, token: str, voice_clip: Path, case_name: str) -> dict[str, Any]:
    profile_id = f"profile-{case_name}-{uuid.uuid4().hex[:8]}"
    return http_json(
        "POST",
        base_url + "/v1/voice-profiles/upload",
        token=token,
        payload={
            "profile_id": profile_id,
            "voice_id": f"voice-{case_name}",
            "display_name": f"Hapa Optional {case_name}",
            "description": "Operator voice clip for optional engine testing.",
            "default_mode": "flow",
            "filename": voice_clip.name,
            "clip_base64": base64.b64encode(voice_clip.read_bytes()).decode("ascii"),
            "traits": {"source": "attached_voice_clip", "matrix_case": case_name},
            "request_hints": {"reference_text": REFERENCE_TEXT},
        },
        timeout=20,
    )


def run_api_case(*, case_name: str, tts_engine: str, mode: str, out_dir: Path, voice_clip: Path, env_overrides: dict[str, str], timeout_seconds: float) -> dict[str, Any]:
    report: dict[str, Any] = {"case": case_name, "tts_engine": tts_engine, "mode": mode, "ok": False, "status": "failed", "env_overrides": {k: v for k, v in env_overrides.items() if "TOKEN" not in k}}
    process, base_url, token, log_path = launch_server(case_name, out_dir, env_overrides)
    report["base_url"] = base_url
    report["log_path"] = str(log_path)
    try:
        health = wait_for_health(base_url, process, log_path)
        caps = http_json("GET", base_url + "/capabilities", token=token, timeout=10)
        upload = upload_profile(base_url, token, voice_clip, case_name)
        profile = upload.get("voice_profile") or {}
        command = {
            "api_version": "v1",
            "command_id": f"optional-{case_name}-{uuid.uuid4().hex[:8]}",
            "actor": "tests:optional-engine-matrix",
            "kind": "synthesize",
            "mode": mode,
            "payload": {
                "text": SCRIPT,
                "tts_engine": tts_engine,
                "voice_profile_id": profile.get("profile_id"),
                "ref_text": REFERENCE_TEXT,
                "output": {"format": "wav", "mint_card": False, "cymatica_bundle": False},
            },
            "provenance": {"source_node": "hapa-drama", "surface": "optional-engine-matrix"},
            "options": {},
        }
        started = time.monotonic()
        report["health"] = health
        report["capabilities_engines"] = caps.get("engines", {})
        try:
            result = http_json("POST", base_url + "/v1/commands", token=token, payload=command, timeout=timeout_seconds + 30)
            generation = result.get("generation") or {}
            audio_path = Path(str(generation.get("audio_path") or ""))
            inspection = inspect_wav(audio_path)
            report.update(
                {
                    "ok": bool(result.get("ok") and generation.get("status") == "succeeded"),
                    "status": "succeeded",
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "generation_id": generation.get("generation_id"),
                    "engine": generation.get("engine"),
                    "audio_path": str(audio_path),
                    "duration_seconds": round(inspection.duration_seconds, 3),
                    "sample_rate": inspection.sample_rate,
                    "normalized_rms": round(inspection.normalized_rms, 6),
                    "engine_metadata": generation.get("engine_metadata") or {},
                }
            )
        except Exception as exc:
            error = str(exc)
            report.update({"ok": False, "elapsed_seconds": round(time.monotonic() - started, 3), "error": error})
            if tts_engine in {"dramabox", "dramabox-cuda"} and ("without CUDA" in error or "cannot import torch" in error or "not configured" in error):
                report["status"] = "blocked"
        return report
    except Exception as exc:
        report["error"] = str(exc)
        return report
    finally:
        stop_server(process)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run optional Chatterbox and DramaBox engine tests through Hapa Drama.")
    parser.add_argument("--voice-clip", default=str(DEFAULT_VOICE_CLIP))
    parser.add_argument("--out-dir", default=str(ROOT / "artifacts" / "optional_engines"))
    parser.add_argument("--chatterbox-timeout-seconds", type=float, default=float(os.environ.get("HAPA_DRAMA_CHATTERBOX_TIMEOUT_SECONDS") or 300))
    parser.add_argument("--dramabox-timeout-seconds", type=float, default=float(os.environ.get("HAPA_DRAMA_DRAMABOX_TIMEOUT_SECONDS") or 180))
    parser.add_argument("--mlx-dramabox-timeout-seconds", type=float, default=float(os.environ.get("HAPA_DRAMA_MLX_DRAMABOX_TIMEOUT_SECONDS") or 1200))
    parser.add_argument("--skip-mlx-dramabox", action="store_true", help="Do not run the Apple Silicon DramaBox MLX case.")
    parser.add_argument("--strict-dramabox", action="store_true", help="Fail overall when DramaBox is blocked by missing CUDA or model environment.")
    args = parser.parse_args()

    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "optional_engine_matrix_latest.json"
    voice_clip = Path(args.voice_clip).expanduser().resolve()
    if not voice_clip.is_file():
        report = {"ok": False, "error": f"voice clip not found: {voice_clip}"}
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 1

    reference = normalize_reference_audio(voice_clip, out_dir)
    mlx_cli_candidate = ROOT / "upstream" / "mlx-audio" / ".venv" / "bin" / "mlx_audio.tts.generate"
    mlx_cli = mlx_cli_candidate.resolve() if mlx_cli_candidate.is_file() else None
    cases = [
        run_api_case(
            case_name="chatterbox-standard",
            tts_engine="chatterbox",
            mode="flow",
            out_dir=out_dir,
            voice_clip=voice_clip,
            timeout_seconds=args.chatterbox_timeout_seconds,
            env_overrides={
                "HAPA_DRAMA_ENABLE_CHATTERBOX": "1",
                "HAPA_DRAMA_CHATTERBOX_ROOT": str(ROOT / "upstream" / "chatterbox"),
                "HAPA_DRAMA_CHATTERBOX_PYTHON": str(ROOT / "upstream" / "chatterbox" / ".venv" / "bin" / "python"),
                "HAPA_DRAMA_CHATTERBOX_MODEL": "standard",
                "HAPA_DRAMA_CHATTERBOX_TIMEOUT_SECONDS": str(args.chatterbox_timeout_seconds),
                "HAPA_DRAMA_ENABLE_DRAMABOX": "0",
                "HAPA_DRAMA_ENABLE_MLX_DRAMABOX": "0",
                "HAPA_DRAMA_ENABLE_MLX_AUDIO": "0",
            },
        ),
    ]
    if mlx_cli and not args.skip_mlx_dramabox:
        cases.append(
            run_api_case(
                case_name="dramabox-mlx",
                tts_engine="dramabox-mlx",
                mode="drama",
                out_dir=out_dir,
                voice_clip=voice_clip,
                timeout_seconds=args.mlx_dramabox_timeout_seconds,
                env_overrides={
                    "HAPA_DRAMA_ENABLE_MLX_DRAMABOX": "1",
                    "HAPA_DRAMA_MLX_DRAMABOX_CLI": str(mlx_cli),
                    "HAPA_DRAMA_MLX_DRAMABOX_MODEL": "mlx-community/ResembleAI-Dramabox",
                    "HAPA_DRAMA_MLX_DRAMABOX_REF_TEXT": REFERENCE_TEXT,
                    "HAPA_DRAMA_MLX_DRAMABOX_TIMEOUT_SECONDS": str(args.mlx_dramabox_timeout_seconds),
                    "HAPA_DRAMA_ENABLE_DRAMABOX": "0",
                    "HAPA_DRAMA_ENABLE_CHATTERBOX": "0",
                    "HAPA_DRAMA_ENABLE_MLX_AUDIO": "0",
                },
            )
        )
    cases.append(
        run_api_case(
            case_name="dramabox",
            tts_engine="dramabox-cuda",
            mode="drama",
            out_dir=out_dir,
            voice_clip=voice_clip,
            timeout_seconds=args.dramabox_timeout_seconds,
            env_overrides={
                "HAPA_DRAMA_ENABLE_DRAMABOX": "1",
                "HAPA_DRAMA_DRAMABOX_ROOT": str(ROOT / "upstream" / "DramaBox"),
                "HAPA_DRAMA_DRAMABOX_PYTHON": str(ROOT / "upstream" / "DramaBox" / ".venv" / "bin" / "python"),
                "HAPA_DRAMA_DRAMABOX_TIMEOUT_SECONDS": str(args.dramabox_timeout_seconds),
                "HAPA_DRAMA_ENABLE_CHATTERBOX": "0",
                "HAPA_DRAMA_ENABLE_MLX_DRAMABOX": "0",
                "HAPA_DRAMA_ENABLE_MLX_AUDIO": "0",
            },
        )
    )
    chatterbox_ok = any(case.get("tts_engine") == "chatterbox" and case.get("ok") for case in cases)
    dramabox_mlx_ok = any(case.get("tts_engine") == "dramabox-mlx" and case.get("ok") for case in cases)
    dramabox_cuda_ok = any(case.get("tts_engine") == "dramabox-cuda" and case.get("ok") for case in cases)
    dramabox_cuda_blocked = any(case.get("tts_engine") == "dramabox-cuda" and case.get("status") == "blocked" for case in cases)
    overall_ok = bool(reference.get("ok") and chatterbox_ok and (dramabox_mlx_ok or dramabox_cuda_ok or (dramabox_cuda_blocked and not args.strict_dramabox)))
    report = {
        "ok": overall_ok,
        "voice_clip": str(voice_clip),
        "reference_wav": reference,
        "cases": cases,
        "summary": {
            "chatterbox_success": chatterbox_ok,
            "dramabox_mlx_success": dramabox_mlx_ok,
            "dramabox_cuda_success": dramabox_cuda_ok,
            "dramabox_cuda_blocked": dramabox_cuda_blocked,
            "strict_dramabox": bool(args.strict_dramabox),
        },
    }
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
