from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from threading import Lock
from typing import Any

from .config import Settings, utc_now_iso

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS events (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT NOT NULL UNIQUE,
  command_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  time TEXT NOT NULL,
  payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS generations (
  generation_id TEXT PRIMARY KEY,
  command_id TEXT NOT NULL,
  mode TEXT NOT NULL,
  engine TEXT NOT NULL,
  status TEXT NOT NULL,
  text_hash TEXT,
  audio_path TEXT,
  audio_sha256 TEXT,
  duration_seconds REAL,
  sample_rate INTEGER,
  engine_metadata_json TEXT NOT NULL DEFAULT '{}',
  card_id TEXT,
  cymatica_bundle_path TEXT,
  cymatica_handoff_path TEXT,
  cymatica_handoff_zip_path TEXT,
  voice_id TEXT,
  voice_profile_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS voices (
  voice_id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  entanglement_level INTEGER NOT NULL DEFAULT 0,
  xp INTEGER NOT NULL DEFAULT 0,
  generation_count INTEGER NOT NULL DEFAULT 0,
  traits_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS voice_profiles (
  profile_id TEXT PRIMARY KEY,
  voice_id TEXT NOT NULL,
  display_name TEXT NOT NULL,
  description TEXT,
  default_mode TEXT NOT NULL DEFAULT 'auto',
  clip_generation_id TEXT,
  clip_audio_path TEXT,
  clip_audio_sha256 TEXT,
  traits_json TEXT NOT NULL DEFAULT '{}',
  request_hints_json TEXT NOT NULL DEFAULT '{}',
  created_by TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""


class DramaStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = Lock()
        self._conn = sqlite3.connect(str(settings.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA_SQL)
        self._migrate_schema()
        self._conn.commit()
        settings.event_log_path.parent.mkdir(parents=True, exist_ok=True)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _migrate_schema(self) -> None:
        columns = {row["name"] for row in self._conn.execute("PRAGMA table_info(generations)").fetchall()}
        for name in ["cymatica_handoff_path", "cymatica_handoff_zip_path", "voice_id", "voice_profile_id"]:
            if name not in columns:
                self._conn.execute(f"ALTER TABLE generations ADD COLUMN {name} TEXT")
        if "duration_seconds" not in columns:
            self._conn.execute("ALTER TABLE generations ADD COLUMN duration_seconds REAL")
        if "sample_rate" not in columns:
            self._conn.execute("ALTER TABLE generations ADD COLUMN sample_rate INTEGER")
        if "engine_metadata_json" not in columns:
            self._conn.execute("ALTER TABLE generations ADD COLUMN engine_metadata_json TEXT NOT NULL DEFAULT '{}'")

    def append_event(self, event: dict[str, Any]) -> int:
        payload_json = json.dumps(event.get("payload") or {}, sort_keys=True)
        with self._lock:
            with self.settings.event_log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, sort_keys=True) + "\n")
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO events(event_id, command_id, kind, time, payload_json) VALUES (?, ?, ?, ?, ?)",
                (event["event_id"], event["command_id"], event["kind"], event["time"], payload_json),
            )
            self._conn.commit()
            if cur.lastrowid:
                return int(cur.lastrowid)
            row = self._conn.execute("SELECT seq FROM events WHERE event_id = ?", (event["event_id"],)).fetchone()
            return int(row["seq"] if row else 0)

    def list_events(self, since: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT seq, event_id, command_id, kind, time, payload_json FROM events WHERE seq > ? ORDER BY seq ASC LIMIT ?",
            (int(since), int(limit)),
        ).fetchall()
        return [
            {
                "seq": int(row["seq"]),
                "event_id": row["event_id"],
                "command_id": row["command_id"],
                "kind": row["kind"],
                "time": row["time"],
                "payload": json.loads(row["payload_json"]),
            }
            for row in rows
        ]

    def list_events_for_command(self, command_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT seq, event_id, command_id, kind, time, payload_json FROM events WHERE command_id = ? ORDER BY seq ASC",
            (command_id,),
        ).fetchall()
        return [
            {
                "seq": int(row["seq"]),
                "event_id": row["event_id"],
                "command_id": row["command_id"],
                "kind": row["kind"],
                "time": row["time"],
                "payload": json.loads(row["payload_json"]),
            }
            for row in rows
        ]

    def latest_event_seq(self) -> int:
        row = self._conn.execute("SELECT COALESCE(MAX(seq), 0) AS seq FROM events").fetchone()
        return int(row["seq"] if row else 0)

    def upsert_generation(self, item: dict[str, Any]) -> None:
        now = utc_now_iso()
        engine_metadata_json = json.dumps(item.get("engine_metadata") if isinstance(item.get("engine_metadata"), dict) else {}, sort_keys=True)
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO generations(generation_id, command_id, mode, engine, status, text_hash, audio_path, audio_sha256, duration_seconds, sample_rate, engine_metadata_json, card_id, cymatica_bundle_path, cymatica_handoff_path, cymatica_handoff_zip_path, voice_id, voice_profile_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(generation_id) DO UPDATE SET
                  mode=excluded.mode,
                  engine=excluded.engine,
                  status=excluded.status,
                  audio_path=excluded.audio_path,
                  audio_sha256=excluded.audio_sha256,
                  duration_seconds=excluded.duration_seconds,
                  sample_rate=excluded.sample_rate,
                  engine_metadata_json=excluded.engine_metadata_json,
                  card_id=excluded.card_id,
                  cymatica_bundle_path=excluded.cymatica_bundle_path,
                  cymatica_handoff_path=excluded.cymatica_handoff_path,
                  cymatica_handoff_zip_path=excluded.cymatica_handoff_zip_path,
                  voice_id=excluded.voice_id,
                  voice_profile_id=excluded.voice_profile_id,
                  updated_at=excluded.updated_at
                """,
                (
                    item["generation_id"],
                    item["command_id"],
                    item["mode"],
                    item["engine"],
                    item["status"],
                    item.get("text_hash"),
                    item.get("audio_path"),
                    item.get("audio_sha256"),
                    item.get("duration_seconds"),
                    item.get("sample_rate"),
                    engine_metadata_json,
                    item.get("card_id"),
                    item.get("cymatica_bundle_path"),
                    item.get("cymatica_handoff_path"),
                    item.get("cymatica_handoff_zip_path"),
                    item.get("voice_id"),
                    item.get("voice_profile_id"),
                    item.get("created_at") or now,
                    now,
                ),
            )
            self._conn.commit()

    def _generation_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["engine_metadata"] = json.loads(item.pop("engine_metadata_json") or "{}")
        return item

    def get_generation(self, generation_id: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM generations WHERE generation_id = ?", (generation_id,)).fetchone()
        return self._generation_from_row(row) if row else None

    def list_generations(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._conn.execute("SELECT * FROM generations ORDER BY created_at DESC LIMIT ?", (int(limit),)).fetchall()
        return [self._generation_from_row(row) for row in rows]

    def create_voice(self, voice_id: str, display_name: str, traits: dict[str, Any] | None = None) -> dict[str, Any]:
        now = utc_now_iso()
        traits_json = json.dumps(traits or {}, sort_keys=True)
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO voices(voice_id, display_name, traits_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(voice_id) DO UPDATE SET
                  display_name=excluded.display_name,
                  traits_json=excluded.traits_json,
                  updated_at=excluded.updated_at
                """,
                (voice_id, display_name, traits_json, now, now),
            )
            self._conn.commit()
        return self.get_voice(voice_id) or {}

    def get_voice(self, voice_id: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM voices WHERE voice_id = ?", (voice_id,)).fetchone()
        if not row:
            return None
        out = dict(row)
        out["traits"] = json.loads(out.pop("traits_json") or "{}")
        return out

    def list_voices(self) -> list[dict[str, Any]]:
        rows = self._conn.execute("SELECT * FROM voices ORDER BY updated_at DESC").fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["traits"] = json.loads(item.pop("traits_json") or "{}")
            out.append(item)
        return out

    def entangle_voice(self, voice_id: str, xp_delta: int) -> dict[str, Any]:
        now = utc_now_iso()
        with self._lock:
            self._conn.execute(
                """
                UPDATE voices
                SET xp = xp + ?,
                    generation_count = generation_count + 1,
                    entanglement_level = CAST((xp + ?) / 100 AS INTEGER),
                    updated_at = ?
                WHERE voice_id = ?
                """,
                (int(xp_delta), int(xp_delta), now, voice_id),
            )
            self._conn.commit()
        voice = self.get_voice(voice_id)
        if not voice:
            raise ValueError("voice_id not found")
        return voice

    def create_voice_profile(self, item: dict[str, Any]) -> dict[str, Any]:
        now = utc_now_iso()
        traits_json = json.dumps(item.get("traits") if isinstance(item.get("traits"), dict) else {}, sort_keys=True)
        request_hints_json = json.dumps(item.get("request_hints") if isinstance(item.get("request_hints"), dict) else {}, sort_keys=True)
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO voice_profiles(profile_id, voice_id, display_name, description, default_mode, clip_generation_id, clip_audio_path, clip_audio_sha256, traits_json, request_hints_json, created_by, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(profile_id) DO UPDATE SET
                  voice_id=excluded.voice_id,
                  display_name=excluded.display_name,
                  description=excluded.description,
                  default_mode=excluded.default_mode,
                  clip_generation_id=excluded.clip_generation_id,
                  clip_audio_path=excluded.clip_audio_path,
                  clip_audio_sha256=excluded.clip_audio_sha256,
                  traits_json=excluded.traits_json,
                  request_hints_json=excluded.request_hints_json,
                  created_by=excluded.created_by,
                  updated_at=excluded.updated_at
                """,
                (
                    item["profile_id"],
                    item["voice_id"],
                    item["display_name"],
                    item.get("description"),
                    item.get("default_mode") or "auto",
                    item.get("clip_generation_id"),
                    item.get("clip_audio_path"),
                    item.get("clip_audio_sha256"),
                    traits_json,
                    request_hints_json,
                    item.get("created_by"),
                    item.get("created_at") or now,
                    now,
                ),
            )
            self._conn.commit()
        return self.get_voice_profile(item["profile_id"]) or {}

    def get_voice_profile(self, profile_id: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM voice_profiles WHERE profile_id = ?", (profile_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["traits"] = json.loads(item.pop("traits_json") or "{}")
        item["request_hints"] = json.loads(item.pop("request_hints_json") or "{}")
        return item

    def list_voice_profiles(self) -> list[dict[str, Any]]:
        rows = self._conn.execute("SELECT * FROM voice_profiles ORDER BY updated_at DESC").fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["traits"] = json.loads(item.pop("traits_json") or "{}")
            item["request_hints"] = json.loads(item.pop("request_hints_json") or "{}")
            out.append(item)
        return out
