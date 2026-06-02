# AGENTS.md — Hapa Drama

## Node identity

- Repo: this repository root
- Node id: `.hapaDrama`
- Package/API service: `hapa-drama`
- Status: active Hapa node app, Mac-first loopback voice synthesis service with CLI, API, web UI, Electron wrapper, and SwiftUI skeleton.

## Source of truth

- Human overview: `README.md`
- Surface parity: `docs/FEATURE_PARITY.md`
- API contract: `docs/API.md`
- Command envelope: `docs/COMMAND_SCHEMA.md`
- Desktop protocol: `docs/DESKTOP_ELECTRON.md`
- Verification protocol: `docs/TESTING_PROTOCOL.md`
- Main FastAPI app: `python/hapa_drama_node/app.py`
- CLI: `python/hapa_drama_node/cli.py`
- Router/core feature spine: `python/hapa_drama_node/router.py`
- Web UI: `web/index.html`, `web/app.js`, `web/app.css`

## Safe edit boundaries

- Safe to edit application source, tests, docs, and launch scripts in this repo.
- Do not commit or publish `.node_token`, SQLite data, generated audio, model weights, local reference clips, or runtime artifacts.
- Treat `data/`, `artifacts/`, `upstream/`, `.venv/`, and `node_modules/` as local/runtime dependency state unless a task explicitly targets them.
- Keep loopback bearer-token behavior intact for non-public endpoints.

## Hapa node-app standard checklist

When changing a core capability, update all applicable surfaces or mark the gap truthfully in `docs/FEATURE_PARITY.md`:

1. API: `/health`, `/capabilities`, or `/v1/*` route.
2. CLI: `hapa-drama ...` command or documented absent/partial state.
3. UI: web/Electron operator control or documented absent/partial state.
4. Docs: README and protocol docs describe the capability.
5. Verification: add or update a syntax/unit/smoke check.

The UI must keep a Docs / README / Protocol / Help surface that renders repo `README.md` through `/docs/readme` with provenance and safe Markdown behavior.

## Verification gates

Use the smallest repo-appropriate check that validates your change:

```bash
PYTHONPATH=python python -m pytest tests -q
python -m compileall python/hapa_drama_node tests scripts
npm run check:electron
node --check web/app.js
python -m json.tool package.json >/dev/null
```

For service-level smoke when dependencies are installed and the local port is free:

```bash
hapa-drama serve
hapa-drama health
TOKEN="$(cat .node_token)" hapa-drama capabilities
```

## Known caveats

- Optional clone engines are environment-dependent. DramaBox, Chatterbox, MLX-Audio, Piper, and CUDA readiness should be reported as ready/configured/blocked, not assumed.
- macOS speech and deterministic stub fallbacks allow local tests without large external model installs.
- This repo is currently an untracked working tree on branch `main`; inspect `git status --short` before editing and avoid overwriting unrelated local changes.
