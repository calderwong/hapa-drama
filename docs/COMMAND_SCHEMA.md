# Hapa Drama Command Schema

All UI, CLI, API, and inter-node calls use the same envelope.

```json
{
  "api_version": "v1",
  "command_id": "uuid",
  "actor": "ui:hapa-drama|cli:hapa-drama|node:<id>",
  "kind": "synthesize",
  "mode": "auto|drama|flow|ultrafast",
  "payload": {},
  "provenance": {},
  "options": {}
}
```

Initial command kinds:

- `synthesize`
- `voice.create`
- `voice.profile.create`
- `voice.profile.get`
- `voice.profile.list`
- `voice.update`
- `voice.entangle`
- `voice.rate_generation`
- `generation.get`
- `generation.list`
- `cymatica.layer`
- `card.mint`
- `analyze.audio`

Parity rule: every surface must submit this envelope unchanged except for `actor` and `provenance.surface`.

Profile-aware synthesis payload:

```json
{
  "text": "line to synthesize",
  "tts_engine": "optional: chatterbox|dramabox|dramabox-mlx|dramabox-cuda|mlx-audio|macos-speech",
  "voice_id": "optional voice identity",
  "voice_profile_id": "optional reusable Profile id",
  "voice_clip_path": "optional direct reference clip path",
  "chatterbox_model": "optional: standard|turbo",
  "emotion": { "style": "neutral|dramatic|whisper|...", "intensity": 0.25 },
  "timing": { "bpm": 120, "start_seconds": 0, "target_duration_seconds": null },
  "output": { "format": "wav", "mint_card": true, "cymatica_bundle": true },
  "request": { "requested_by": "node:<id>|agent:<id>" }
}
```

Voice Profiles bind a reusable voice identity to an optional seed clip:

```json
{
  "profile_id": "profile-narrator",
  "voice_id": "voice-narrator",
  "display_name": "Narrator",
  "description": "Reusable narrator voice",
  "default_mode": "auto|flow|drama|ultrafast",
  "clip_generation_id": "existing generation id",
  "traits": {},
  "request_hints": {}
}
```
