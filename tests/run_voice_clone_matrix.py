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
from hapa_drama_node.engines.mlx_audio_adapter import resolve_mlx_audio_cli


DEFAULT_VOICE_CLIP = Path(os.environ.get("HAPA_DRAMA_TEST_VOICE_CLIP") or str(ROOT / "data" / "default_voice" / "operator-default-reference.wav"))
REFERENCE_TEXT = "This reference clip was provided by the operator as the source voice for Hapa Drama profile synthesis."
SCRIPTS = [
    "Hapa Drama profile test one. The node is speaking the requested script through the selected voice route.",
    "Hapa Drama profile test two. This confirms the output is longer than a silent one second artifact.",
    "Hapa Drama profile test three. The attached voice clip is bound to the request as the profile reference.",
]


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


def http_bytes(method: str, url: str, *, token: str | None = None, timeout: float = 60.0) -> bytes:
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return res.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc


def wait_for_health(base_url: str, process: subprocess.Popen[bytes], log_path: Path, timeout_seconds: float = 20.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_error = ""
    while time.monotonic() < deadline:
        if process.poll() is not None:
            log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
            raise RuntimeError(f"server exited early with code {process.returncode}; log={log[-4000:]}")
        try:
            health = http_json("GET", base_url + "/health", timeout=1.0)
            if health.get("ok") is True:
                return health
        except Exception as exc:
            last_error = str(exc)
        time.sleep(0.2)
    raise RuntimeError(f"server did not become healthy: {last_error}")


def run_command(command: list[str], *, timeout: float) -> dict[str, Any]:
    started = time.monotonic()
    try:
        completed = subprocess.run(command, check=True, capture_output=True, text=True, timeout=timeout)
        return {
            "ok": True,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "stdout_tail": completed.stdout[-2000:],
            "stderr_tail": completed.stderr[-2000:],
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "error": f"timeout after {timeout:.0f}s",
            "stdout_tail": (exc.stdout or "")[-2000:] if isinstance(exc.stdout, str) else "",
            "stderr_tail": (exc.stderr or "")[-2000:] if isinstance(exc.stderr, str) else "",
        }
    except subprocess.CalledProcessError as exc:
        return {
            "ok": False,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "error": f"exit code {exc.returncode}",
            "stdout_tail": (exc.stdout or "")[-2000:],
            "stderr_tail": (exc.stderr or "")[-2000:],
        }


def probe_source_audio(path: Path) -> dict[str, Any]:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return {"path": str(path), "exists": path.is_file(), "bytes": path.stat().st_size if path.exists() else 0}
    result = run_command(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration,size:stream=codec_name,sample_rate,channels",
            "-of",
            "json",
            str(path),
        ],
        timeout=15,
    )
    payload: dict[str, Any] = {"path": str(path), "exists": path.is_file(), "bytes": path.stat().st_size if path.exists() else 0, "ffprobe": result}
    if result.get("ok"):
        try:
            payload["media"] = json.loads(str(result.get("stdout_tail") or "{}"))
        except json.JSONDecodeError:
            pass
    return payload


def normalize_reference_audio(source: Path, out_dir: Path) -> dict[str, Any]:
    ref_dir = out_dir / "reference"
    ref_dir.mkdir(parents=True, exist_ok=True)
    ref_path = ref_dir / "profile-reference-24k.wav"
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return {"ok": False, "error": "ffmpeg not found", "path": str(ref_path)}
    result = run_command(
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
        timeout=45,
    )
    result["path"] = str(ref_path)
    if result.get("ok"):
        inspection = assert_audible_wav(ref_path, min_duration_seconds=0.5, min_normalized_rms=0.0005)
        result["inspection"] = {
            "duration_seconds": round(inspection.duration_seconds, 3),
            "sample_rate": inspection.sample_rate,
            "channels": inspection.channels,
            "normalized_rms": round(inspection.normalized_rms, 6),
        }
    return result


def launch_server(case_name: str, out_dir: Path, env_overrides: dict[str, str]) -> tuple[subprocess.Popen[bytes], str, str, Path]:
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    token = f"hapa-drama-matrix-{uuid.uuid4().hex}"
    runtime_dir = out_dir / "runtime" / case_name
    log_path = out_dir / "logs" / f"{case_name}.log"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    python_path = str(ROOT / "python")
    if env.get("PYTHONPATH"):
        python_path = python_path + os.pathsep + str(env["PYTHONPATH"])
    env.update(
        {
            "PYTHONPATH": python_path,
            "HAPA_DRAMA_TOKEN": token,
            "HAPA_DRAMA_TOKEN_FILE": str(runtime_dir / ".node_token"),
            "HAPA_DRAMA_STORAGE_DIR": str(runtime_dir / "data"),
            "HAPA_DRAMA_ARTIFACTS_DIR": str(runtime_dir / "artifacts"),
            "HAPA_DRAMA_RUNTIME_FILE": str(runtime_dir / "runtime" / "hapa_drama_runtime.json"),
            "HAPA_DRAMA_HOST": "127.0.0.1",
            "HAPA_DRAMA_PORT": str(port),
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


def stop_server(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def upload_profile(base_url: str, token: str, voice_clip: Path, case_name: str, default_mode: str) -> dict[str, Any]:
    profile_id = f"profile-{case_name}-{uuid.uuid4().hex[:8]}"
    raw = voice_clip.read_bytes()
    return http_json(
        "POST",
        base_url + "/v1/voice-profiles/upload",
        token=token,
        payload={
            "profile_id": profile_id,
            "voice_id": f"voice-{case_name}",
            "display_name": f"Hapa Matrix {case_name}",
            "description": "Attached operator voice clip used as the profile reference.",
            "default_mode": default_mode,
            "filename": voice_clip.name,
            "clip_base64": base64.b64encode(raw).decode("ascii"),
            "traits": {"source": "attached_voice_clip", "matrix_case": case_name},
            "request_hints": {"reference_text": REFERENCE_TEXT},
        },
        timeout=20,
    )


def save_generation_audio(base_url: str, token: str, generation: dict[str, Any], dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    audio_path = Path(str(generation.get("audio_path") or ""))
    if audio_path.is_file():
        shutil.copyfile(audio_path, dest)
    else:
        generation_id = str(generation.get("generation_id") or "")
        dest.write_bytes(http_bytes("GET", base_url + f"/v1/generations/{generation_id}/audio", token=token, timeout=30))
    return dest


def run_api_case(
    *,
    case_name: str,
    out_dir: Path,
    voice_clip: Path,
    env_overrides: dict[str, str],
    mode: str,
    profile_default_mode: str,
    script_count: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    case_report: dict[str, Any] = {
        "case": case_name,
        "mode": mode,
        "profile_default_mode": profile_default_mode,
        "env_overrides": {k: v for k, v in env_overrides.items() if "TOKEN" not in k},
        "ok": False,
        "results": [],
    }
    process, base_url, token, log_path = launch_server(case_name, out_dir, env_overrides)
    case_report["base_url"] = base_url
    case_report["log_path"] = str(log_path)
    try:
        health = wait_for_health(base_url, process, log_path)
        capabilities = http_json("GET", base_url + "/capabilities", token=token, timeout=5)
        profile_upload = upload_profile(base_url, token, voice_clip, case_name, profile_default_mode)
        profile = profile_upload.get("voice_profile") or {}
        profile_id = str(profile.get("profile_id") or "")
        case_report["health"] = health
        case_report["capabilities_engines"] = capabilities.get("engines", {})
        case_report["profile"] = profile
        for index, text in enumerate(SCRIPTS[:script_count], start=1):
            command = {
                "api_version": "v1",
                "command_id": f"matrix-{case_name}-{index}-{uuid.uuid4().hex[:6]}",
                "actor": "tests:voice-clone-matrix",
                "kind": "synthesize",
                "mode": mode,
                "payload": {
                    "text": text,
                    "voice_profile_id": profile_id,
                    "ref_text": REFERENCE_TEXT,
                    "output": {"format": "wav", "mint_card": False, "cymatica_bundle": False},
                },
                "provenance": {"source_node": "hapa-drama", "surface": "voice-clone-matrix"},
                "options": {},
            }
            started = time.monotonic()
            result: dict[str, Any] = {"index": index, "text": text}
            try:
                synth = http_json("POST", base_url + "/v1/commands", token=token, payload=command, timeout=timeout_seconds + 30)
                generation = synth.get("generation") or {}
                dest = out_dir / "successes" / f"{case_name}-{index}.wav"
                save_generation_audio(base_url, token, generation, dest)
                inspection = inspect_wav(dest)
                metadata = generation.get("engine_metadata") or {}
                result.update(
                    {
                        "ok": bool(synth.get("ok") and generation.get("status") == "succeeded"),
                        "elapsed_seconds": round(time.monotonic() - started, 3),
                        "generation_id": generation.get("generation_id"),
                        "engine": generation.get("engine"),
                        "selected_mode": generation.get("mode"),
                        "audio_path": str(dest),
                        "duration_seconds": round(inspection.duration_seconds, 3),
                        "sample_rate": inspection.sample_rate,
                        "normalized_rms": round(inspection.normalized_rms, 6),
                        "voice_clone_requested": bool(metadata.get("voice_clone_requested") or metadata.get("voice_clip_path")),
                        "voice_clone_supported": bool(metadata.get("voice_clone_supported")),
                        "engine_metadata": metadata,
                    }
                )
            except Exception as exc:
                result.update({"ok": False, "elapsed_seconds": round(time.monotonic() - started, 3), "error": str(exc)})
            case_report["results"].append(result)
        case_report["ok"] = any(bool(item.get("ok")) for item in case_report["results"])
        return case_report
    except Exception as exc:
        case_report["error"] = str(exc)
        return case_report
    finally:
        stop_server(process)


def build_cases(args: argparse.Namespace, mlx_cli: Path | None) -> list[dict[str, Any]]:
    cases = [
        {
            "case_name": "macos-auto-profile",
            "mode": "auto",
            "profile_default_mode": "auto",
            "script_count": 2,
            "timeout_seconds": 60.0,
            "env_overrides": {
                "HAPA_DRAMA_ENABLE_MACOS_SPEECH": "1",
                "HAPA_DRAMA_ENABLE_MLX_AUDIO": "0",
                "HAPA_DRAMA_ENABLE_DRAMABOX": "0",
                "HAPA_DRAMA_ENABLE_PIPER": "0",
                "HAPA_DRAMA_STUB_SUCCESS": "1",
            },
        },
        {
            "case_name": "macos-flow-profile",
            "mode": "flow",
            "profile_default_mode": "flow",
            "script_count": 1,
            "timeout_seconds": 60.0,
            "env_overrides": {
                "HAPA_DRAMA_ENABLE_MACOS_SPEECH": "1",
                "HAPA_DRAMA_ENABLE_MLX_AUDIO": "0",
                "HAPA_DRAMA_ENABLE_DRAMABOX": "0",
                "HAPA_DRAMA_ENABLE_PIPER": "0",
                "HAPA_DRAMA_STUB_SUCCESS": "1",
            },
        },
        {
            "case_name": "macos-drama-profile",
            "mode": "drama",
            "profile_default_mode": "drama",
            "script_count": 1,
            "timeout_seconds": 60.0,
            "env_overrides": {
                "HAPA_DRAMA_ENABLE_MACOS_SPEECH": "1",
                "HAPA_DRAMA_ENABLE_MLX_AUDIO": "0",
                "HAPA_DRAMA_ENABLE_DRAMABOX": "0",
                "HAPA_DRAMA_ENABLE_PIPER": "0",
                "HAPA_DRAMA_STUB_SUCCESS": "1",
            },
        },
        {
            "case_name": "stub-no-macos",
            "mode": "flow",
            "profile_default_mode": "flow",
            "script_count": 1,
            "timeout_seconds": 60.0,
            "env_overrides": {
                "HAPA_DRAMA_ENABLE_MACOS_SPEECH": "0",
                "HAPA_DRAMA_ENABLE_MLX_AUDIO": "0",
                "HAPA_DRAMA_ENABLE_DRAMABOX": "0",
                "HAPA_DRAMA_ENABLE_PIPER": "0",
                "HAPA_DRAMA_STUB_SUCCESS": "1",
            },
        },
    ]
    if args.try_mlx and mlx_cli:
        cases.append(
            {
                "case_name": "mlx-reference-flow",
                "mode": "flow",
                "profile_default_mode": "flow",
                "script_count": 2,
                "timeout_seconds": float(args.mlx_timeout_seconds),
                "env_overrides": {
                    "HAPA_DRAMA_ENABLE_MACOS_SPEECH": "1",
                    "HAPA_DRAMA_ENABLE_MLX_AUDIO": "1",
                    "HAPA_DRAMA_MLX_AUDIO_CLI": str(mlx_cli),
                    "HAPA_DRAMA_MLX_AUDIO_MODEL": str(args.mlx_model),
                    "HAPA_DRAMA_MLX_AUDIO_REF_TEXT": REFERENCE_TEXT,
                    "HAPA_DRAMA_MLX_AUDIO_TIMEOUT_SECONDS": str(args.mlx_timeout_seconds),
                    "HAPA_DRAMA_ENABLE_DRAMABOX": "0",
                    "HAPA_DRAMA_ENABLE_PIPER": "0",
                    "HAPA_DRAMA_STUB_SUCCESS": "1",
                },
            }
        )
    return cases


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Hapa Drama voice profile and clone-route matrix tests.")
    parser.add_argument("--voice-clip", default=str(DEFAULT_VOICE_CLIP))
    parser.add_argument("--out-dir", default=str(ROOT / "artifacts" / "clone_matrix"))
    parser.add_argument("--try-mlx", action="store_true", help="Also try the MLX-Audio reference/clone route when the CLI is available.")
    parser.add_argument("--mlx-model", default=os.environ.get("HAPA_DRAMA_MLX_AUDIO_MODEL") or "mlx-community/IndexTTS")
    parser.add_argument("--mlx-timeout-seconds", type=float, default=float(os.environ.get("HAPA_DRAMA_MLX_AUDIO_TIMEOUT_SECONDS") or 120))
    args = parser.parse_args()

    voice_clip = Path(args.voice_clip).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "clone_matrix_latest.json"
    if not voice_clip.is_file():
        report = {"ok": False, "error": f"voice clip not found: {voice_clip}"}
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 1

    mlx_cli = resolve_mlx_audio_cli()
    report: dict[str, Any] = {
        "ok": False,
        "voice_clip": probe_source_audio(voice_clip),
        "reference_wav": normalize_reference_audio(voice_clip, out_dir),
        "mlx_audio": {"cli_path": str(mlx_cli) if mlx_cli else None, "requested": bool(args.try_mlx), "model": args.mlx_model},
        "cases": [],
        "successes": [],
        "clone_capable_successes": [],
    }

    for case in build_cases(args, mlx_cli):
        case_report = run_api_case(out_dir=out_dir, voice_clip=voice_clip, **case)
        report["cases"].append(case_report)
        for result in case_report.get("results", []):
            if result.get("ok"):
                report["successes"].append(
                    {
                        "case": case_report.get("case"),
                        "engine": result.get("engine"),
                        "mode": result.get("selected_mode"),
                        "audio_path": result.get("audio_path"),
                        "duration_seconds": result.get("duration_seconds"),
                        "normalized_rms": result.get("normalized_rms"),
                    }
                )
                if result.get("voice_clone_supported"):
                    report["clone_capable_successes"].append(result)

    report["ok"] = len(report["successes"]) >= 3 and bool(report.get("reference_wav", {}).get("ok"))
    report["summary"] = {
        "success_count": len(report["successes"]),
        "clone_capable_success_count": len(report["clone_capable_successes"]),
        "note": "macOS speech successes bind the uploaded clip as a Hapa voice profile reference; true voice cloning requires an MLX model that supports ref_audio.",
    }
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
