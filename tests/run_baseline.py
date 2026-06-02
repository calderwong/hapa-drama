from __future__ import annotations

import tempfile
import uuid
from argparse import Namespace
from pathlib import Path

from hapa_drama_node.audio import inspect_wav
from hapa_drama_node.cli import build_synthesize_command
from hapa_drama_node.config import load_settings
from hapa_drama_node.cymatica import validate_cymatica_bundle, validate_cymatica_handoff
from hapa_drama_node.persistence import DramaStore
from hapa_drama_node.router import DramaRouter


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_cli_envelope() -> None:
    args = Namespace(
        text="hello",
        script=None,
        command_id="cmd-1",
        actor="cli:test",
        mode="flow",
        voice_id="voice-1",
        voice_profile_id="profile-1",
        requester_node="node:test",
        emotion_style="neutral",
        emotion_intensity=0.2,
        bpm=120.0,
        start_seconds=0.0,
        target_duration_seconds=None,
        no_card=False,
        no_cymatica=False,
    )
    command = build_synthesize_command(args)
    assert_true(command["api_version"] == "v1", "CLI envelope api_version mismatch")
    assert_true(command["kind"] == "synthesize", "CLI envelope kind mismatch")
    assert_true(command["mode"] == "flow", "CLI envelope mode mismatch")
    assert_true(command["payload"]["voice_profile_id"] == "profile-1", "CLI voice profile mismatch")
    assert_true(command["payload"]["request"]["requested_by"] == "node:test", "CLI requester node mismatch")
    assert_true(command["provenance"]["surface"] == "cli", "CLI provenance surface mismatch")


def test_router_synthesis() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        import os

        old_cwd = Path.cwd()
        old_env = {key: os.environ.get(key) for key in ["HAPA_DRAMA_STORAGE_DIR", "HAPA_DRAMA_ARTIFACTS_DIR", "HAPA_DRAMA_TOKEN_FILE"]}
        try:
            os.chdir(root)
            os.environ["HAPA_DRAMA_STORAGE_DIR"] = str(root / "data")
            os.environ["HAPA_DRAMA_ARTIFACTS_DIR"] = str(root / "artifacts")
            os.environ["HAPA_DRAMA_TOKEN_FILE"] = str(root / ".node_token")
            settings = load_settings()
            store = DramaStore(settings)
            router = DramaRouter(settings, store)
            result = router.dispatch(
                {
                    "api_version": "v1",
                    "command_id": str(uuid.uuid4()),
                    "actor": "test",
                    "kind": "synthesize",
                    "mode": "flow",
                    "payload": {"text": "hello hapa drama", "output": {"mint_card": True, "cymatica_bundle": True}},
                    "provenance": {"source_node": "test"},
                    "options": {},
                }
            )
            generation = result["generation"]
            assert_true(result["ok"] is True, "synthesis did not return ok")
            assert_true(Path(generation["audio_path"]).exists(), "audio output missing")
            inspection = inspect_wav(generation["audio_path"])
            assert_true(inspection.duration_seconds >= 0.25, "audio output is too short")
            assert_true(inspection.normalized_rms >= 0.0005, "audio output appears silent")
            assert_true(generation["card_id"].startswith("drama-audio-"), "card id missing")
            assert_true(Path(generation["cymatica_bundle_path"]).exists(), "cymatica bundle missing")
            cymatica_report = validate_cymatica_bundle(generation["cymatica_bundle_path"])
            assert_true(cymatica_report["ok"] is True, "cymatica bundle validation failed")
            assert_true(Path(generation["cymatica_handoff_path"]).exists(), "cymatica handoff missing")
            assert_true(Path(generation["cymatica_handoff_zip_path"]).exists(), "cymatica handoff zip missing")
            handoff_report = validate_cymatica_handoff(generation["cymatica_handoff_path"])
            handoff_zip_report = validate_cymatica_handoff(generation["cymatica_handoff_zip_path"])
            assert_true(handoff_report["ok"] is True, "cymatica handoff validation failed")
            assert_true(handoff_zip_report["ok"] is True, "cymatica handoff zip validation failed")
            store.close()
        finally:
            os.chdir(old_cwd)
            for key, value in old_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def test_voice_entanglement() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        import os

        old_cwd = Path.cwd()
        old_env = {key: os.environ.get(key) for key in ["HAPA_DRAMA_STORAGE_DIR", "HAPA_DRAMA_TOKEN_FILE"]}
        try:
            os.chdir(root)
            os.environ["HAPA_DRAMA_STORAGE_DIR"] = str(root / "data")
            os.environ["HAPA_DRAMA_TOKEN_FILE"] = str(root / ".node_token")
            settings = load_settings()
            store = DramaStore(settings)
            router = DramaRouter(settings, store)
            router.dispatch(
                {
                    "api_version": "v1",
                    "command_id": str(uuid.uuid4()),
                    "actor": "test",
                    "kind": "voice.create",
                    "mode": "auto",
                    "payload": {"voice_id": "voice-test", "display_name": "Test Voice"},
                }
            )
            updated = router.dispatch(
                {
                    "api_version": "v1",
                    "command_id": str(uuid.uuid4()),
                    "actor": "test",
                    "kind": "voice.entangle",
                    "mode": "auto",
                    "payload": {"voice_id": "voice-test", "xp_delta": 125},
                }
            )
            assert_true(updated["voice"]["xp"] == 125, "voice XP mismatch")
            assert_true(updated["voice"]["entanglement_level"] == 1, "voice entanglement level mismatch")
            store.close()
        finally:
            os.chdir(old_cwd)
            for key, value in old_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def test_voice_profile_requests() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        import os

        old_cwd = Path.cwd()
        old_env = {key: os.environ.get(key) for key in ["HAPA_DRAMA_STORAGE_DIR", "HAPA_DRAMA_ARTIFACTS_DIR", "HAPA_DRAMA_TOKEN_FILE"]}
        try:
            os.chdir(root)
            os.environ["HAPA_DRAMA_STORAGE_DIR"] = str(root / "data")
            os.environ["HAPA_DRAMA_ARTIFACTS_DIR"] = str(root / "artifacts")
            os.environ["HAPA_DRAMA_TOKEN_FILE"] = str(root / ".node_token")
            settings = load_settings()
            store = DramaStore(settings)
            router = DramaRouter(settings, store)
            clip = router.dispatch(
                {
                    "api_version": "v1",
                    "command_id": str(uuid.uuid4()),
                    "actor": "test",
                    "kind": "synthesize",
                    "mode": "flow",
                    "payload": {"text": "profile seed clip", "output": {"mint_card": True, "cymatica_bundle": True}},
                    "provenance": {"source_node": "test"},
                    "options": {},
                }
            )
            created = router.dispatch(
                {
                    "api_version": "v1",
                    "command_id": str(uuid.uuid4()),
                    "actor": "test",
                    "kind": "voice.profile.create",
                    "mode": "auto",
                    "payload": {
                        "profile_id": "profile-narrator",
                        "voice_id": "voice-narrator",
                        "display_name": "Narrator",
                        "default_mode": "drama",
                        "clip_generation_id": clip["generation"]["generation_id"],
                        "traits": {"tone": "warm"},
                        "request_hints": {"best_for": "inter-node dialogue"},
                    },
                    "provenance": {"source_node": "test"},
                    "options": {},
                }
            )
            assert_true(created["voice_profile"]["profile_id"] == "profile-narrator", "profile id mismatch")
            requested = router.dispatch(
                {
                    "api_version": "v1",
                    "command_id": str(uuid.uuid4()),
                    "actor": "node:test-agent",
                    "kind": "synthesize",
                    "mode": "auto",
                    "payload": {
                        "text": "use the narrator profile",
                        "voice_profile_id": "profile-narrator",
                        "request": {"requested_by": "node:test-agent"},
                        "output": {"mint_card": True, "cymatica_bundle": True},
                    },
                    "provenance": {"source_node": "node:test-agent"},
                    "options": {},
                }
            )
            generation = requested["generation"]
            assert_true(generation["voice_profile_id"] == "profile-narrator", "generation profile mismatch")
            assert_true(generation["voice_id"] == "voice-narrator", "generation voice mismatch")
            assert_true(generation["mode"] == "drama", "profile default mode was not applied")
            store.close()
        finally:
            os.chdir(old_cwd)
            for key, value in old_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def main() -> int:
    tests = [test_cli_envelope, test_router_synthesis, test_voice_entanglement, test_voice_profile_requests]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"ok: {len(tests)} baseline tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
