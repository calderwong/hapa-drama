from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

DramaMode = Literal["auto", "drama", "flow", "ultrafast"]
DramaCommandKind = Literal[
    "synthesize",
    "voice.create",
    "voice.profile.create",
    "voice.profile.get",
    "voice.profile.list",
    "voice.update",
    "voice.entangle",
    "voice.rate_generation",
    "generation.get",
    "generation.list",
    "cymatica.layer",
    "card.mint",
    "analyze.audio",
]


@dataclass(frozen=True)
class DramaCommand:
    api_version: str
    command_id: str
    actor: str
    kind: str
    mode: str
    payload: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "DramaCommand":
        if not isinstance(data, dict):
            raise ValueError("command must be an object")
        api_version = str(data.get("api_version") or "v1").strip()
        command_id = str(data.get("command_id") or "").strip()
        actor = str(data.get("actor") or "anonymous").strip()
        kind = str(data.get("kind") or "").strip()
        mode = str(data.get("mode") or "auto").strip().lower()
        payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
        provenance = data.get("provenance") if isinstance(data.get("provenance"), dict) else {}
        options = data.get("options") if isinstance(data.get("options"), dict) else {}
        if api_version != "v1":
            raise ValueError("api_version must be v1")
        if not command_id:
            raise ValueError("command_id is required")
        if not kind:
            raise ValueError("kind is required")
        if mode not in {"auto", "drama", "flow", "ultrafast"}:
            raise ValueError("mode must be one of: auto, drama, flow, ultrafast")
        return DramaCommand(
            api_version=api_version,
            command_id=command_id,
            actor=actor or "anonymous",
            kind=kind,
            mode=mode,
            payload=payload,
            provenance=provenance,
            options=options,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "api_version": self.api_version,
            "command_id": self.command_id,
            "actor": self.actor,
            "kind": self.kind,
            "mode": self.mode,
            "payload": self.payload,
            "provenance": self.provenance,
            "options": self.options,
        }


@dataclass(frozen=True)
class DramaEvent:
    event_id: str
    command_id: str
    kind: str
    sequence: int
    time: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "command_id": self.command_id,
            "kind": self.kind,
            "sequence": self.sequence,
            "time": self.time,
            "payload": self.payload,
        }
