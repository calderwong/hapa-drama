# Hapa Drama Feature Parity

Status vocabulary follows the Hapa node-app standard: `verified`, `partial`, `scaffold`, `blocked`, `unknown`, `deprecated`.

## Surface map

| Capability | API | CLI | UI | Data/source | Auth | Verification | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Health/status | `GET /health` | `hapa-drama health` | Status badges | app settings + engine readiness | public loopback | `tests/run_api_smoke.py`, manual curl/CLI smoke | verified |
| Capabilities/protocol advert | `GET /capabilities` | `hapa-drama capabilities` | Mode guide + runtime rendering | `python/hapa_drama_node/app.py` | bearer | API smoke, capabilities JSON inspection | verified |
| Synthesize voice clip | `POST /v1/commands` kind `synthesize` | `hapa-drama synthesize` | Forge Clip + Simple Mode | `DramaRouter.dispatch` | bearer | `tests/test_router.py`, `tests/test_cli.py`, baseline smoke | verified |
| Voice creation | `POST /v1/commands` kind `voice.create` | `hapa-drama voice-create` | Cultivator Entanglement panel seeds voice IDs indirectly | `DramaStore` | bearer | `tests/test_router.py` | partial: UI does not expose a standalone voice-create form |
| Voice Profile create/list/get | `POST /v1/commands`, `GET /v1/voice-profiles`, `GET /v1/voice-profiles/{id}` | `voice-profile-create`, `voice-profiles`, `voice-profile-get` | Add Your Voice Clip, Library, selectors | `DramaStore` | bearer | `tests/test_router.py`, `tests/run_baseline.py` | verified |
| Browser voice recording/upload | `POST /v1/voice-profiles/upload` | no direct CLI upload wrapper; use profile-create with existing clip generation | Record Voice + Upload Clip | browser WAV encoder + `DramaStore` | bearer | UI smoke/manual; syntax checks | partial: CLI upload wrapper absent |
| Default voice route | `GET/PUT /v1/default-route`, `/local/session` bootstrap | environment + synthesize defaults; no dedicated default-route CLI command | Default Voice controls + Simple Mode | `data/default_route.json`, env settings | bearer except local session loopback | UI/API smoke; code syntax | partial: CLI reads defaults but cannot set route directly |
| Generation process telemetry | `GET /v1/generations/{id}/process`, `GET /v1/telemetry` | `self-test` reports generation checks | Process Monitor, timeline, recent generations | `DramaStore` events/process records | bearer | baseline/self-test | verified |
| Assets download | generation audio/card/cymatica endpoints | `synthesize --save-audio`, cymatica validators | Director Track asset buttons + audio preview | artifact root guarded by `_safe_file` | bearer | router tests and syntax checks | verified |
| Cymatica handoff | generation cymatica endpoints | `cymatica-validate`, `cymatica-handoff-validate` | checkbox + asset buttons | `python/hapa_drama_node/cymatica.py` | bearer | `tests/test_router.py`, `tests/run_baseline.py` | verified |
| Flow voiceover queue | `POST/GET /v1/flow-voiceovers/*` | `scripts/queue_flow_voiceovers.py` | represented in capabilities/process assets; no dedicated queue authoring panel | `python/hapa_drama_node/flow_voiceovers.py` | bearer for mutation; loopback public manifest/audio | script syntax + existing manifests | partial: UI authoring/control panel is not full parity |
| README/docs viewer | `GET /docs/readme` | `hapa-drama docs` (local README by default, `--from-api` for endpoint parity) | Docs / README / Protocol / Help panel renders README.md | repo-root `README.md` | loopback-only public | `tests/test_docs.py`, `node --check web/app.js` | verified for README minimum; partial for multi-doc browser |
| Desktop wrapper | same loopback API through Electron | `npm run desktop`, launcher scripts | Electron shell wraps web UI | `electron/main.cjs`, launcher scripts | loopback bearer | `npm run check:electron` | verified syntax; runtime smoke depends on desktop environment |
| SwiftUI app skeleton | none beyond planned loopback use | Xcode/SwiftPM package | `Apps/HapaDramaApp` skeleton | Swift package | n/a | not run in this pass | scaffold |

## Current compliance determination

Hapa Drama is an active Hapa node app. After the 2026-05-26 healing pass it has human docs, AI-agent operating context, a feature parity matrix, and a UI README viewer that renders repo `README.md` from a loopback docs endpoint with provenance and no source-HTML execution.

Compliance is partial, not absolute: core synthesize/profile/telemetry/cymatica surfaces are verified or syntax-checked, while browser upload CLI parity, default-route CLI mutation, full flow-voiceover UI authoring, and SwiftUI parity remain explicitly partial/scaffold.
