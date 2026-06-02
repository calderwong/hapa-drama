from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import Settings, utc_now_iso


def mint_audio_card(settings: Settings, generation: dict[str, Any], command: dict[str, Any]) -> dict[str, Any]:
    card_id = f"drama-audio-{generation['generation_id']}"
    card_dir = settings.artifacts_dir / "cards" / card_id
    card_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "type": "card",
        "id": card_id,
        "kind": "audio",
        "title": f"Hapa Drama Audio {generation['generation_id']}",
        "createdAt": utc_now_iso(),
        "audio": {
            "localPath": generation.get("audio_path"),
            "mimeType": "audio/wav",
            "sha256": generation.get("audio_sha256"),
            "durationSeconds": generation.get("duration_seconds"),
            "sampleRate": generation.get("sample_rate"),
        },
        "hapa": {
            "node": "hapa-drama",
            "generation_id": generation["generation_id"],
            "command_id": generation["command_id"],
            "mode": generation["mode"],
            "engine": generation["engine"],
            "engine_metadata": generation.get("engine_metadata") or {},
            "provenance": command.get("provenance") or {},
        },
    }
    record_path = card_dir / "card.json"
    record_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return {"card_id": card_id, "card_path": str(record_path), "record": record}
