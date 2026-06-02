# Hapa Drama API

Default launcher base URL: `http://127.0.0.1:8758`

Public endpoints:

- `GET /`
- `GET /health`
- `GET /docs/readme` (loopback-only README Markdown payload for the UI Docs viewer)

Authenticated endpoints require `Authorization: Bearer <token>`:

- `GET /capabilities`
- `POST /v1/commands`
- `GET /v1/events?since=0&limit=100`
- `GET /v1/voices`
- `GET /v1/voice-profiles`
- `POST /v1/voice-profiles/upload`
- `GET /v1/default-route`
- `PUT /v1/default-route`
- `GET /v1/generations`
- `GET /v1/generations/{generation_id}`
- `GET /v1/generations/{generation_id}/process`
- `GET /v1/generations/{generation_id}/audio`
- `GET /v1/generations/{generation_id}/card`
- `GET /v1/generations/{generation_id}/cymatica-manifest`
- `GET /v1/peers`
- `GET /v1/telemetry`

Asset download endpoints are scoped to persisted generation records and only serve files inside the node artifact root.

`/docs/readme` returns repo-root `README.md` as JSON with `source_path`, `sha256`, `provenance`, `safe_markdown`, and raw Markdown `content`. It is loopback-only and intended for the web/Electron **Docs / README / Protocol / Help** panel. The UI renderer must not execute Markdown HTML/scripts.

`/v1/generations/{generation_id}/process` returns Hapa process state for UI/desktop surfaces: `status`, `stage`, numeric `progress`, `timeline`, `assets`, and final `outcome`.

`/v1/telemetry` returns node-level health/status/metrics plus `recent_processes` for dashboard rendering.

Generated audio is validated before a command can succeed. Process outcomes include `duration_seconds`, `sample_rate`, and backend metadata such as the selected model, clone-reference path, device, or macOS system voice.

Engine selection is available through `payload.tts_engine`:

- `chatterbox`: ResembleAI Chatterbox voice clone route.
- `dramabox`: ResembleAI DramaBox expressive clone route. On Apple Silicon this prefers the MLX DramaBox backend when `HAPA_DRAMA_ENABLE_MLX_DRAMABOX=1`; use `dramabox-cuda` to force upstream PyTorch/CUDA.
- `dramabox-mlx`: ResembleAI DramaBox via MLX-Audio and `mlx-community/ResembleAI-Dramabox`.
- `dramabox-cuda`: Upstream ResembleAI DramaBox PyTorch/CUDA route.
- `mlx-audio`: Legacy MLX-Audio / IndexTTS route. The launcher keeps this on the older compatible Pinokio CLI when present; the newer repo-local MLX-Audio venv is reserved for DramaBox MLX.
- `macos-speech`: local macOS `say` fallback route.

When a synthesize command omits engine and voice fields, the node applies its `default_route` from `/local/session` and `/capabilities`. Operators can seed `profile-operator-default` from `HAPA_DRAMA_DEFAULT_VOICE_CLIP_PATH` or the ignored local file `data/default_voice/operator-default-reference.wav`; default requests route through `tts_engine=dramabox` unless overridden.

DramaBox expects quoted dialogue inside a scene prompt. For ordinary script text, the node wraps the text before dispatching to DramaBox MLX and prepares profile clips as short de-silenced references. To provide your own DramaBox scene prompt, send `payload.dramabox_prompt`; to adjust the automatic wrapper, send `payload.dramabox_speaker` and `payload.dramabox_style`.

The UI recorder creates a WAV in the browser and saves it through `POST /v1/voice-profiles/upload`. Use `PUT /v1/default-route` with `voice_profile_id`, `voice_id`, `voice_display_name`, `mode`, and `tts_engine` to persist the default voice used by future UI, CLI, and API synthesize calls. Only send `reference_text` when it is the actual transcript/caption of the reference clip, and mark it with `reference_text_is_transcript=true`; descriptive notes are intentionally not forwarded to clone engines as `--ref_text`.

`GET /health` reports each optional engine's enabled/ready state. DramaBox may be configured but not ready on non-CUDA Macs.
