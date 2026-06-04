# Hapa Drama

`hapa-drama` is a Mac-first Hapa voice synthesis node for expressive narration, fast local TTS, and Cymatica voice-stem layering.

Current scaffold (`v0.1.0`):

- FastAPI loopback service with bearer auth.
- Standard `/health`, `/capabilities`, `/v1/commands`, `/v1/events`, `/v1/voices`, `/v1/generations`, `/v1/peers`, and `/v1/telemetry` endpoints.
- CLI binary: `hapa-drama`.
- macOS speech backend that writes audible spoken-script `.wav` files, with deterministic stub fallback.
- Optional Chatterbox, DramaBox, and MLX-Audio adapters selectable per request with `payload.tts_engine`.
- Voice Cultivator persistence with XP/entanglement.
- Card JSON minting scaffold for generated audio.
- Cymatica bundle scaffold with timing manifest.
- Hapa telemetry UI with process badges, generation timeline, assets, and outcome state.
- Electron desktop wrapper around the same loopback web UI.
- SwiftUI/SwiftPM app skeleton.

## Hapa Ecosystem Context

Hapa is built as a constellation of modular nodes. Each node owns a focused capability, but participates in a shared protocol for provenance, handoff, cards, memory, and operations.

Every node is designed for both human operators and AI agents. The target contract is three surfaces: a UI for direct human review/control, an API for node-to-node and agent calls, and a CLI for scripted runs, audits, and handoffs. Individual repos may be at different maturity levels, but the public contract is that humans and agents can inspect, operate, and verify the node.

Hapa nodes power AI agents and avatar-agents that build new nodes and enhance existing ones. As work moves through the ecosystem, it is mined for utility, wisdom, and repeatable logic, then distilled into Hapa Cards: portable packets of skills, context, memories, and operational patterns.

Humans and AIs use Hapa Cards to discuss, ideate, prototype, and deploy increasingly complex workflows through a playable, card-collecting mechanic. Collaboration history, skills, work artifacts, and canonical decisions are stored in [hapa-second-brain](https://github.com/calderwong/hapa-second-brain), enriched into [Hapa Worldbuilding Wiki](https://github.com/calderwong/hapa-worldbuilding-wiki) entries, and converted back into cards. Avatar-agents can also be combined or specialized into purpose-built identities with their own storage, lore, canon, card decks, skills, and protocols.

## Quick start

```bash
cd <hapa-drama repo>
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .

hapa-drama serve
```

In another shell:

```bash
cd <hapa-drama repo>
source .venv/bin/activate
TOKEN="$(cat .node_token)"
hapa-drama health
hapa-drama capabilities --token "$TOKEN"
hapa-drama synthesize --token "$TOKEN" --mode flow --text "Hapa Drama is online." --save-audio artifacts/manual/hapa-drama.wav
```

## Hapa interfaces

- Browser UI: `http://127.0.0.1:8758/` when launched through `scripts/launch_hapa_drama.sh`
- Desktop UI: `scripts/launch_hapa_drama.sh --electron`
- CLI: `hapa-drama ...`
- CLI docs: `hapa-drama docs`
- API: `POST /v1/commands`
- Docs viewer: UI **Docs / README / Protocol / Help** panel, backed by `GET /docs/readme`

All surfaces use the same command envelope documented in `docs/COMMAND_SCHEMA.md`.

## Related Hapa nodes

- [Hapa MLX Station](https://github.com/calderwong/hapa-mlx-station) — Media-generation hub that can supply or consume voice/audio artifacts.
- [Hapa Song Registry](https://github.com/calderwong/hapa-song-registry) — Music and timing registry that complements narration, lyrics, and voice-stem outputs.
- [Hapa Living Comic](https://github.com/calderwong/hapa-living-comic) — Narrative panel surface that can use generated narration and spoken character lines.
- [Cymatica](https://github.com/calderwong/cymatica) — Spatial audio and stem-to-3D experiments that can receive Drama voice bundles.
- [Hapa Space](https://github.com/calderwong/hapa-space) — Fleet runtime that can surface generated voice/telemetry as node ship context.
- [Overwatch](https://github.com/calderwong/overwatch) — Operational board and evidence spine for generated media work.

## Hapa operating contract

Hapa Drama is an active Hapa node app, not a passive library or archived production record. Its core feature spine is `python/hapa_drama_node/router.py`; API, CLI, web UI, Electron, and docs should either expose the same capability or mark the missing surface truthfully in `docs/FEATURE_PARITY.md`.

Primary inputs:

- Hapa command envelopes (`api_version`, `command_id`, `actor`, `kind`, `mode`, `payload`, `provenance`, `options`).
- Script text and optional timing/emotion parameters.
- Optional voice identity/profile/reference-clip fields.
- Optional local engine environment variables for DramaBox, Chatterbox, MLX-Audio, Piper, and macOS speech.

Primary outputs:

- Validated WAV audio.
- Generation/process records in local storage.
- Card JSON and Cymatica manifests/handoff bundles when requested.
- Telemetry events for Hapa dashboards and neighboring nodes.

Related Hapa surfaces:

- Feature parity matrix: `docs/FEATURE_PARITY.md`
- API details: `docs/API.md`
- Command envelope: `docs/COMMAND_SCHEMA.md`
- Desktop protocol: `docs/DESKTOP_ELECTRON.md`
- AI-agent operating context: `AGENTS.md`

## UI README / Markdown viewer

The web/Electron UI includes a **Docs / README / Protocol / Help** panel near the top of the shell. It fetches `GET /docs/readme`, shows the repo-root README provenance and SHA-256, and renders Markdown through a small allowlisted renderer in `web/app.js`.

Safe Markdown behavior: the UI builds DOM nodes with `textContent`; source Markdown HTML and scripts are not passed through as executable HTML. Links are only activated for `http(s)` and root-relative URLs; other link targets render as text.

## Verification

Repo-appropriate checks for this node:

```bash
pip install -e ".[dev]"
PYTHONPATH=python python -m pytest tests -q
python -m compileall python/hapa_drama_node tests scripts
npm run check:electron
node --check web/app.js
python -m json.tool package.json >/dev/null
```

Service smoke when local dependencies are installed and the port is available:

```bash
hapa-drama serve
hapa-drama docs
hapa-drama health
TOKEN="$(cat .node_token)" hapa-drama capabilities
```

## Desktop launcher

```bash
scripts/launch_hapa_drama.sh --build
scripts/launch_hapa_drama.sh --electron
```

Double-click launchers:

- `$HOME/Desktop/Hapa Drama.app`
- `launch_hapa_drama_desktop.command`
- `$HOME/Desktop/Launch Hapa Drama.command`

Reinstall the `.app` launcher with:

```bash
scripts/install_desktop_launcher.sh
```

For live backend/UI development:

```bash
scripts/launch_hapa_drama.sh --watch
```

See `docs/DESKTOP_ELECTRON.md` for the desktop/watch protocol.

## Optional engines

Heavy clone engines are isolated from the base app and can be installed into `upstream/`:

- Chatterbox: ResembleAI Chatterbox voice cloning, Mac/MPS capable through `upstream/chatterbox/.venv`.
- Drama mode: DramaBox expressive voice cloning. Apple Silicon uses the MLX conversion (`mlx-community/ResembleAI-Dramabox`) through latest `mlx-audio`; CUDA hosts can still use upstream PyTorch DramaBox.
- Local default: macOS `say` + `afconvert`, producing spoken-script WAV output without network access.
- Flow mode: MLX-Audio through `mlx_audio.tts.generate` when `HAPA_DRAMA_ENABLE_MLX_AUDIO=1`.
- UltraFast mode: Piper.

Until those are installed and enabled, the node routes to macOS speech when available, then to the deterministic stub engine. Uploaded clips become reusable Hapa voice Profiles and provenance references; true voice cloning requires a clone-capable backend such as Chatterbox, MLX-Audio, or DramaBox.

Install or refresh the optional upstream engines:

```bash
scripts/install_optional_engines.sh chatterbox
scripts/install_optional_engines.sh dramabox
scripts/install_optional_engines.sh mlx-dramabox
```

Select an engine from the desktop UI or force one in the command payload:

```json
{
  "kind": "synthesize",
  "mode": "flow",
  "payload": {
    "text": "Hapa Drama is online.",
    "tts_engine": "chatterbox",
    "voice_profile_id": "profile-my-voice"
  }
}
```

CLI equivalent:

```bash
hapa-drama synthesize --token "$TOKEN" --mode flow --tts-engine chatterbox --voice-profile-id profile-my-voice --text "Hapa Drama is online."
```

DramaBox is wired as `tts_engine=dramabox`. On Apple Silicon, the launcher prefers `dramabox-mlx` when `upstream/mlx-audio/.venv/bin/mlx_audio.tts.generate` is installed:

```bash
export HAPA_DRAMA_ENABLE_MLX_DRAMABOX=1
export HAPA_DRAMA_MLX_DRAMABOX_CLI="$PWD/upstream/mlx-audio/.venv/bin/mlx_audio.tts.generate"
export HAPA_DRAMA_MLX_DRAMABOX_MODEL="mlx-community/ResembleAI-Dramabox"
```

The desktop launcher can seed a default profile from `HAPA_DRAMA_DEFAULT_VOICE_CLIP_PATH` or the ignored local file `data/default_voice/operator-default-reference.wav` when present. Plain UI, CLI, and API synthesize calls default to:

```bash
HAPA_DRAMA_DEFAULT_MODE=drama
HAPA_DRAMA_DEFAULT_TTS_ENGINE=dramabox
HAPA_DRAMA_DEFAULT_VOICE_PROFILE_ID=profile-operator-default
```

The UI Simple Mode uses only that route: script in, DramaBox MLX voice WAV out.

The web and Electron UI can also record a new voice sample directly from the microphone. Use **Record Voice**, preview the captured WAV, then **Save Recording**. With **Set as default voice** checked, the app writes `data/default_route.json`, selects the new Profile for the current run, and reloads it for future UI, CLI, and API synthesize calls. Recorded clips are saved as reference audio only; the app does not send descriptive notes as `ref_text` unless you provide an actual transcript/caption and mark it as one.

DramaBox is prompt-driven rather than plain TTS. When a caller sends ordinary script text, Hapa Drama now wraps it as quoted dialogue before calling DramaBox, and it prepares the default voice clip as a short de-silenced 48 kHz stereo reference for the MLX backend. Advanced callers can bypass the wrapper with `payload.dramabox_prompt` or tune the wrapper with `payload.dramabox_speaker` and `payload.dramabox_style`.

Use `tts_engine=dramabox-cuda` to force the upstream PyTorch/CUDA backend. That path expects CUDA-class hardware and large model downloads; on non-CUDA Macs, `/health` reports it as configured but not ready unless `HAPA_DRAMA_DRAMABOX_ALLOW_CPU=1` is set for an experimental CPU attempt.

MLX-Audio can be pointed at an existing Pinokio install or any compatible CLI:

```bash
export HAPA_DRAMA_ENABLE_MLX_AUDIO=1
export HAPA_DRAMA_MLX_AUDIO_CLI="/path/to/mlx_audio.tts.generate"
export HAPA_DRAMA_MLX_AUDIO_MODEL="mlx-community/IndexTTS"
```

The desktop launcher auto-detects compatible local MLX-Audio CLI installs and enables `mlx-community/IndexTTS` for explicit legacy MLX-Audio requests. Flow requests with an uploaded voice profile prefer Chatterbox when it is ready; the newer repo-local `upstream/mlx-audio/.venv` is reserved for DramaBox MLX because current MLX-Audio's IndexTTS loader is not compatible with the older `mlx-community/IndexTTS` config.

Run the attached-clip profile matrix with:

```bash
PYTHONPATH=python .venv/bin/python tests/run_voice_clone_matrix.py --voice-clip "$HAPA_DRAMA_TEST_VOICE_CLIP" --try-mlx
```

Run the Chatterbox/DramaBox option test matrix with:

```bash
PYTHONPATH=python .venv/bin/python tests/run_optional_engine_matrix.py --voice-clip "$HAPA_DRAMA_TEST_VOICE_CLIP"
```

## Security

- Loopback bind by default.
- Bearer auth for non-public endpoints.
- `.node_token` is generated locally and gitignored.
- Generated audio, databases, model weights, and artifacts are runtime data.

## SwiftUI app skeleton

Open the package in Xcode:

```bash
open Apps/HapaDramaApp/Package.swift
```

The SwiftUI skeleton is intentionally thin; parity-critical behavior lives in the node command contract first.
