from __future__ import annotations

import uuid
from pathlib import Path

from hapa_drama_node.audio import inspect_wav
from hapa_drama_node.config import load_settings
from hapa_drama_node.cymatica import validate_cymatica_handoff
from hapa_drama_node.persistence import DramaStore
from hapa_drama_node.router import DramaRouter


def test_synthesize_stub_writes_audio_card_and_cymatica(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HAPA_DRAMA_STORAGE_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("HAPA_DRAMA_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("HAPA_DRAMA_TOKEN_FILE", str(tmp_path / ".node_token"))
    settings = load_settings()
    store = DramaStore(settings)
    router = DramaRouter(settings, store)
    command_id = str(uuid.uuid4())
    result = router.dispatch(
        {
            "api_version": "v1",
            "command_id": command_id,
            "actor": "test",
            "kind": "synthesize",
            "mode": "flow",
            "payload": {"text": "hello hapa drama", "output": {"mint_card": True, "cymatica_bundle": True}},
            "provenance": {"source_node": "test"},
            "options": {},
        }
    )
    assert result["ok"] is True
    generation = result["generation"]
    assert generation["status"] == "succeeded"
    assert generation["audio_path"].endswith("voice.wav")
    audio = inspect_wav(generation["audio_path"])
    assert audio.duration_seconds >= 0.25
    assert audio.normalized_rms >= 0.0005
    assert generation["duration_seconds"] == audio.duration_seconds
    assert generation["card_id"].startswith("drama-audio-")
    assert generation["cymatica_bundle_path"]
    assert Path(generation["cymatica_handoff_zip_path"]).exists()
    assert validate_cymatica_handoff(generation["cymatica_handoff_zip_path"])["ok"] is True
    kinds = [event["kind"] for event in result["events"]]
    assert "command.accepted" in kinds
    assert "card.minted" in kinds
    assert "cymatica.bundle.written" in kinds
    store.close()


def test_voice_entanglement_progresses(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HAPA_DRAMA_STORAGE_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("HAPA_DRAMA_TOKEN_FILE", str(tmp_path / ".node_token"))
    settings = load_settings()
    store = DramaStore(settings)
    router = DramaRouter(settings, store)
    created = router.dispatch(
        {
            "api_version": "v1",
            "command_id": str(uuid.uuid4()),
            "actor": "test",
            "kind": "voice.create",
            "mode": "auto",
            "payload": {"voice_id": "voice-test", "display_name": "Test Voice"},
        }
    )
    assert created["voice"]["voice_id"] == "voice-test"
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
    assert updated["voice"]["xp"] == 125
    assert updated["voice"]["entanglement_level"] == 1
    store.close()


def test_voice_profile_request_uses_profile_defaults(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HAPA_DRAMA_STORAGE_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("HAPA_DRAMA_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("HAPA_DRAMA_TOKEN_FILE", str(tmp_path / ".node_token"))
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
            "payload": {"text": "seed clip", "output": {"mint_card": True, "cymatica_bundle": True}},
        }
    )
    profile = router.dispatch(
        {
            "api_version": "v1",
            "command_id": str(uuid.uuid4()),
            "actor": "test",
            "kind": "voice.profile.create",
            "mode": "auto",
            "payload": {
                "profile_id": "profile-test",
                "voice_id": "voice-test-profile",
                "display_name": "Test Profile",
                "default_mode": "drama",
                "clip_generation_id": clip["generation"]["generation_id"],
            },
        }
    )
    assert profile["voice_profile"]["clip_audio_path"].endswith("voice.wav")
    generated = router.dispatch(
        {
            "api_version": "v1",
            "command_id": str(uuid.uuid4()),
            "actor": "node:test",
            "kind": "synthesize",
            "mode": "auto",
            "payload": {"text": "profile request", "voice_profile_id": "profile-test"},
        }
    )
    assert generated["generation"]["voice_id"] == "voice-test-profile"
    assert generated["generation"]["voice_profile_id"] == "profile-test"
    assert generated["generation"]["mode"] == "drama"
    store.close()
