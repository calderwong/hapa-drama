# Testing Protocol

Baseline tests must pass without real TTS engines installed.

Pass gates:

1. Python modules compile.
2. Dependency-free baseline runner passes.
3. Default synthesis writes a valid, audible `.wav` using macOS speech when available or the deterministic stub fallback.
4. Command events are appended.
5. Card JSON is minted when requested.
6. Cymatica bundle manifest is written when requested.
7. CLI/API use the same command envelope.
8. Managed loopback API smoke passes, including token bootstrap, profile requests, authenticated audio/card/manifest/handoff downloads, and local Cymatica bundle + handoff validation.
9. Telemetry/process smoke passes: synth responses include `process`, `/v1/generations/{generation_id}/process` reports completed/failed outcome, and `/v1/telemetry` lists recent processes.
10. Electron wrapper syntax passes and launcher scripts are shell-syntax valid.
11. Attached voice clip matrix passes with at least three audible profile-bound TTS outputs.

Commands:

```bash
pip install -e ".[dev]"
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q python tests
PYTHONPATH=python PYTHONDONTWRITEBYTECODE=1 python3 tests/run_baseline.py
PYTHONDONTWRITEBYTECODE=1 python3 tests/run_api_smoke.py
PYTHONPATH=python PYTHONDONTWRITEBYTECODE=1 python3 tests/run_voice_clone_matrix.py --voice-clip "$HAPA_DRAMA_TEST_VOICE_CLIP"
node --check electron/main.cjs
bash -n scripts/launch_hapa_drama.sh
bash -n launch_hapa_drama_desktop.command
bash -n "${HAPA_DRAMA_DESKTOP_LAUNCHER:-$HOME/Desktop/Launch Hapa Drama.command}"
PYTHONPATH=python python3 -m hapa_drama_node.cli cymatica-validate --bundle-path artifacts/cymatica/<generation_id>
PYTHONPATH=python python3 -m hapa_drama_node.cli cymatica-handoff-validate --path artifacts/cymatica/<generation_id>/<generation_id>.hapaBundle.zip
swift build --package-path Packages/DramaCore
swift build --package-path Apps/HapaDramaApp
```

Real engine tests are opt-in and should be gated behind explicit environment variables:

- `HAPA_DRAMA_ENABLE_DRAMABOX=1`
- `HAPA_DRAMA_ENABLE_MLX_AUDIO=1`
- `HAPA_DRAMA_MLX_AUDIO_CLI=/path/to/mlx_audio.tts.generate`
- `HAPA_DRAMA_MLX_AUDIO_MODEL=mlx-community/IndexTTS`
- `HAPA_DRAMA_ENABLE_PIPER=1`
- `HAPA_DRAMA_ENABLE_MACOS_SPEECH=0` forces the deterministic stub fallback for dependency-free test runs.

Latency pass/fail targets:

- Flow mode short clip: `<5s` after model warm state.
- UltraFast fallback short clip: best effort below Flow mode.
- Drama mode: quality/provenance first; latency is reported, not initially gated.
