from __future__ import annotations

import json
import shutil
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

from .config import Settings, utc_now_iso
from .provenance import file_sha256, stable_json_hash


def _check(checks: list[dict[str, Any]], name: str, ok: bool, **extra: Any) -> None:
    item: dict[str, Any] = {"name": name, "ok": bool(ok)}
    item.update(extra)
    checks.append(item)


def _epoch_millis() -> int:
    return int(time.time() * 1000)


def _safe_relative_path(path_value: str) -> bool:
    rel = Path(path_value)
    return bool(path_value.strip()) and not rel.is_absolute() and ".." not in rel.parts


def _write_zip_from_directory(source_dir: Path, zip_path: Path) -> None:
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(source_dir).as_posix())


def _extract_zip_safely(zip_path: Path, target_dir: Path) -> None:
    with zipfile.ZipFile(zip_path, "r") as archive:
        for item in archive.infolist():
            rel = Path(item.filename)
            if item.is_dir() or item.filename.startswith("__MACOSX/") or ".DS_Store" in rel.parts:
                continue
            if not _safe_relative_path(item.filename):
                continue
            out_path = (target_dir / rel).resolve()
            root = target_dir.resolve()
            if out_path != root and root not in out_path.parents:
                continue
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(item) as src, out_path.open("wb") as dst:
                shutil.copyfileobj(src, dst)


def write_cymatica_handoff_bundle(settings: Settings, generation: dict[str, Any], command: dict[str, Any], bundle_dir: Path) -> dict[str, Any]:
    generation_id = generation["generation_id"]
    handoff_dir = bundle_dir / "hapa_bundle"
    assets_dir = handoff_dir / "assets"
    cards_dir = handoff_dir / "cards"
    assets_dir.mkdir(parents=True, exist_ok=True)
    cards_dir.mkdir(parents=True, exist_ok=True)
    audio_path = Path(str(generation.get("audio_path") or ""))
    audio_sha = str(generation.get("audio_sha256") or file_sha256(audio_path))
    asset_path = f"assets/{audio_sha}.wav"
    asset_url = handoff_dir / asset_path
    shutil.copyfile(audio_path, asset_url)
    payload = {
        "muted": False,
        "name": "voice",
        "pan": 0,
        "stem_index": 0,
        "vol": 1,
    }
    card = {
        "id": f"hapa-drama-stem-{generation_id}",
        "card_type": "stem",
        "spec_hash": stable_json_hash(payload),
        "artifacts": [
            {
                "name": "voice.wav",
                "path": asset_path,
                "hash": audio_sha,
                "size": asset_url.stat().st_size,
                "type": "audio/wav",
            }
        ],
        "meta": {
            "created_at": _epoch_millis(),
            "created_by": "hapa-drama",
            "supersedes": [],
            "schema_version": "1.0.0",
        },
        "payload": payload,
    }
    card_path = cards_dir / "stem_0.json"
    card_path.write_text(json.dumps(card, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = {
        "version": "1.0.0",
        "session_id": generation_id,
        "export_time": _epoch_millis(),
        "card_paths": ["cards/stem_0.json"],
        "cymatica_version": "1.0.0",
        "export_options": {
            "includeAudio": True,
            "includeKeyframes": False,
            "includeEffectSettings": False,
            "includePromptPackReferences": False,
            "includeShowScript": False,
        },
    }
    manifest_path = handoff_dir / "bundle_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    readme_path = handoff_dir / "README.md"
    readme_path.write_text(f"# Hapa Drama Cymatica Handoff\n\nGeneration ID: {generation_id}\n", encoding="utf-8")
    zip_path = bundle_dir / f"{generation_id}.hapaBundle.zip"
    _write_zip_from_directory(handoff_dir, zip_path)
    return {
        "handoff_path": str(handoff_dir),
        "handoff_zip_path": str(zip_path),
        "bundle_manifest_path": str(manifest_path),
        "stem_card_path": str(card_path),
    }


def write_cymatica_bundle(settings: Settings, generation: dict[str, Any], command: dict[str, Any]) -> dict[str, Any]:
    generation_id = generation["generation_id"]
    bundle_dir = settings.artifacts_dir / "cymatica" / generation_id
    stems_dir = bundle_dir / "stems"
    stems_dir.mkdir(parents=True, exist_ok=True)
    src = Path(str(generation.get("audio_path") or ""))
    stem_path = stems_dir / "voice.wav"
    if src.exists():
        shutil.copyfile(src, stem_path)
    timing = command.get("payload", {}).get("timing") if isinstance(command.get("payload"), dict) else {}
    manifest = {
        "type": "hapa.cymatica.voice_bundle",
        "api_version": "v1",
        "generation_id": generation_id,
        "created_at": utc_now_iso(),
        "stems": [
            {
                "id": "voice",
                "kind": "voice",
                "path": "stems/voice.wav",
                "start_seconds": float((timing or {}).get("start_seconds") or 0),
                "bpm": (timing or {}).get("bpm"),
                "duration_seconds": generation.get("duration_seconds"),
                "sample_rate": generation.get("sample_rate"),
                "source_node": "hapa-drama",
            }
        ],
        "alignment": {
            "target_duration_seconds": (timing or {}).get("target_duration_seconds"),
            "quantize": (timing or {}).get("quantize"),
        },
    }
    manifest_path = bundle_dir / "cymatica_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    handoff = write_cymatica_handoff_bundle(settings, generation, command, bundle_dir)
    return {"bundle_path": str(bundle_dir), "manifest_path": str(manifest_path), "manifest": manifest, **handoff}


def validate_cymatica_bundle(bundle_path: str | Path) -> dict[str, Any]:
    bundle_dir = Path(bundle_path).expanduser().resolve()
    manifest_path = bundle_dir / "cymatica_manifest.json"
    checks: list[dict[str, Any]] = []
    _check(checks, "bundle_directory_exists", bundle_dir.is_dir(), path=str(bundle_dir))
    _check(checks, "manifest_exists", manifest_path.is_file(), path=str(manifest_path))
    manifest: dict[str, Any] = {}
    if manifest_path.is_file():
        try:
            raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(raw_manifest, dict):
                manifest = raw_manifest
            _check(checks, "manifest_json_valid", isinstance(raw_manifest, dict))
        except Exception as exc:
            _check(checks, "manifest_json_valid", False, error=str(exc))
    else:
        _check(checks, "manifest_json_valid", False)
    _check(checks, "manifest_type", manifest.get("type") == "hapa.cymatica.voice_bundle", value=manifest.get("type"))
    _check(checks, "api_version", manifest.get("api_version") == "v1", value=manifest.get("api_version"))
    generation_id = str(manifest.get("generation_id") or "").strip()
    _check(checks, "generation_id_present", bool(generation_id), value=generation_id)
    stems = manifest.get("stems")
    _check(checks, "stems_present", isinstance(stems, list) and len(stems) > 0, count=len(stems) if isinstance(stems, list) else 0)
    valid_stems: list[dict[str, Any]] = []
    if isinstance(stems, list):
        for index, stem in enumerate(stems):
            if not isinstance(stem, dict):
                _check(checks, f"stem_{index}_record", False)
                continue
            _check(checks, f"stem_{index}_id_present", bool(str(stem.get("id") or "").strip()), value=stem.get("id"))
            _check(checks, f"stem_{index}_kind_present", bool(str(stem.get("kind") or "").strip()), value=stem.get("kind"))
            _check(checks, f"stem_{index}_source_node_present", bool(str(stem.get("source_node") or "").strip()), value=stem.get("source_node"))
            try:
                float(stem.get("start_seconds"))
                _check(checks, f"stem_{index}_start_seconds_numeric", True, value=stem.get("start_seconds"))
            except (TypeError, ValueError):
                _check(checks, f"stem_{index}_start_seconds_numeric", False, value=stem.get("start_seconds"))
            rel_path = str(stem.get("path") or "").strip()
            rel = Path(rel_path)
            confined = bool(rel_path) and not rel.is_absolute() and ".." not in rel.parts
            _check(checks, f"stem_{index}_relative_path", confined, path=rel_path)
            stem_path = (bundle_dir / rel).resolve()
            inside_bundle = stem_path == bundle_dir or bundle_dir in stem_path.parents
            _check(checks, f"stem_{index}_inside_bundle", inside_bundle, path=str(stem_path))
            exists = inside_bundle and stem_path.is_file()
            _check(checks, f"stem_{index}_exists", exists, path=str(stem_path))
            size = stem_path.stat().st_size if exists else 0
            _check(checks, f"stem_{index}_nonempty", size > 44, bytes=size)
            is_wav = stem_path.suffix.lower() == ".wav"
            _check(checks, f"stem_{index}_wav_path", is_wav, path=str(stem_path))
            if exists and is_wav:
                with stem_path.open("rb") as stem_file:
                    signature = stem_file.read(4)
                _check(checks, f"stem_{index}_wav_signature", signature == b"RIFF")
            else:
                _check(checks, f"stem_{index}_wav_signature", False)
            valid_stems.append({"id": stem.get("id"), "kind": stem.get("kind"), "path": str(stem_path), "bytes": size})
    return {
        "ok": all(bool(check.get("ok")) for check in checks),
        "bundle_path": str(bundle_dir),
        "manifest_path": str(manifest_path),
        "generation_id": generation_id,
        "stem_count": len(valid_stems),
        "stems": valid_stems,
        "checks": checks,
    }


def validate_cymatica_handoff(path: str | Path) -> dict[str, Any]:
    source_path = Path(path).expanduser().resolve()
    checks: list[dict[str, Any]] = []

    def validate_workspace(workspace: Path) -> dict[str, Any]:
        workspace = workspace.resolve()
        manifest_path = workspace / "bundle_manifest.json"
        _check(checks, "handoff_workspace_exists", workspace.is_dir(), path=str(workspace))
        _check(checks, "bundle_manifest_exists", manifest_path.is_file(), path=str(manifest_path))
        manifest: dict[str, Any] = {}
        if manifest_path.is_file():
            try:
                parsed = json.loads(manifest_path.read_text(encoding="utf-8"))
                if isinstance(parsed, dict):
                    manifest = parsed
                _check(checks, "bundle_manifest_json_valid", isinstance(parsed, dict))
            except Exception as exc:
                _check(checks, "bundle_manifest_json_valid", False, error=str(exc))
        else:
            _check(checks, "bundle_manifest_json_valid", False)
        _check(checks, "bundle_version", manifest.get("version") == "1.0.0", value=manifest.get("version"))
        session_id = str(manifest.get("session_id") or "").strip()
        _check(checks, "session_id_present", bool(session_id), value=session_id)
        _check(checks, "export_time_present", isinstance(manifest.get("export_time"), int), value=manifest.get("export_time"))
        card_paths = manifest.get("card_paths")
        _check(checks, "card_paths_present", isinstance(card_paths, list) and len(card_paths) > 0, count=len(card_paths) if isinstance(card_paths, list) else 0)
        verified_stems: list[dict[str, Any]] = []
        if isinstance(card_paths, list):
            for index, raw_card_path in enumerate(card_paths):
                card_rel_path = str(raw_card_path or "").strip()
                card_path_safe = _safe_relative_path(card_rel_path)
                _check(checks, f"card_{index}_relative_path", card_path_safe, path=card_rel_path)
                card_path = (workspace / card_rel_path).resolve()
                inside_workspace = card_path == workspace or workspace in card_path.parents
                _check(checks, f"card_{index}_inside_workspace", inside_workspace, path=str(card_path))
                card_exists = inside_workspace and card_path.is_file()
                _check(checks, f"card_{index}_exists", card_exists, path=str(card_path))
                if not card_exists:
                    continue
                try:
                    card_raw = json.loads(card_path.read_text(encoding="utf-8"))
                    card = card_raw if isinstance(card_raw, dict) else {}
                    _check(checks, f"card_{index}_json_valid", isinstance(card_raw, dict))
                except Exception as exc:
                    card = {}
                    _check(checks, f"card_{index}_json_valid", False, error=str(exc))
                payload = card.get("payload")
                _check(checks, f"card_{index}_payload_present", isinstance(payload, dict))
                spec_hash = str(card.get("spec_hash") or "")
                computed_spec_hash = stable_json_hash(payload) if isinstance(payload, dict) else ""
                _check(checks, f"card_{index}_spec_hash", bool(spec_hash) and spec_hash == computed_spec_hash, value=spec_hash)
                if card.get("card_type") != "stem":
                    continue
                artifacts = card.get("artifacts")
                _check(checks, f"card_{index}_artifacts_present", isinstance(artifacts, list) and len(artifacts) > 0, count=len(artifacts) if isinstance(artifacts, list) else 0)
                if not isinstance(artifacts, list):
                    continue
                for artifact_index, artifact in enumerate(artifacts):
                    if not isinstance(artifact, dict):
                        _check(checks, f"card_{index}_artifact_{artifact_index}_record", False)
                        continue
                    artifact_rel_path = str(artifact.get("path") or "").strip()
                    artifact_path_safe = _safe_relative_path(artifact_rel_path)
                    _check(checks, f"card_{index}_artifact_{artifact_index}_relative_path", artifact_path_safe, path=artifact_rel_path)
                    artifact_path = (workspace / artifact_rel_path).resolve()
                    artifact_inside = artifact_path == workspace or workspace in artifact_path.parents
                    _check(checks, f"card_{index}_artifact_{artifact_index}_inside_workspace", artifact_inside, path=str(artifact_path))
                    artifact_exists = artifact_inside and artifact_path.is_file()
                    _check(checks, f"card_{index}_artifact_{artifact_index}_exists", artifact_exists, path=str(artifact_path))
                    artifact_size = artifact_path.stat().st_size if artifact_exists else 0
                    _check(checks, f"card_{index}_artifact_{artifact_index}_nonempty", artifact_size > 44, bytes=artifact_size)
                    expected_hash = str(artifact.get("hash") or "")
                    actual_hash = file_sha256(artifact_path) if artifact_exists else ""
                    _check(checks, f"card_{index}_artifact_{artifact_index}_hash", bool(expected_hash) and expected_hash == actual_hash, value=expected_hash)
                    mime_type = str(artifact.get("type") or "")
                    is_audio = artifact_path.suffix.lower() in {".wav", ".aif", ".aiff", ".caf", ".m4a", ".mp3", ".flac"} or mime_type.startswith("audio/")
                    _check(checks, f"card_{index}_artifact_{artifact_index}_audio", is_audio, type=mime_type)
                    if is_audio and artifact_exists:
                        verified_stems.append(
                            {
                                "card_id": card.get("id"),
                                "name": (payload or {}).get("name") if isinstance(payload, dict) else artifact_path.stem,
                                "path": str(artifact_path),
                                "bytes": artifact_size,
                            }
                        )
        _check(checks, "verified_stems_present", len(verified_stems) > 0, count=len(verified_stems))
        return {
            "source_path": str(source_path),
            "workspace_path": str(workspace),
            "session_id": session_id,
            "stem_count": len(verified_stems),
            "stems": verified_stems,
        }

    _check(checks, "source_exists", source_path.exists(), path=str(source_path))
    path_kind = "zip" if source_path.is_file() and source_path.suffix.lower() == ".zip" else "directory"
    if path_kind == "zip":
        _check(checks, "zip_signature", source_path.read_bytes()[:2] == b"PK")
        with tempfile.TemporaryDirectory() as raw_tmp:
            workspace = Path(raw_tmp)
            _extract_zip_safely(source_path, workspace)
            result = validate_workspace(workspace)
    else:
        result = validate_workspace(source_path)
    return {
        "ok": all(bool(check.get("ok")) for check in checks),
        "path_kind": path_kind,
        **result,
        "checks": checks,
    }
