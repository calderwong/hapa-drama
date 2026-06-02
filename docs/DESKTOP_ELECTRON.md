# Desktop Electron Wrapper

Hapa Drama ships as a loopback-first node. The Electron wrapper is a thin desktop shell around the same local FastAPI/web UI so API, CLI, browser UI, and desktop UI stay in parity.

## Standards

- The backend binds to `127.0.0.1` by default.
- Auth remains bearer-token based; the UI obtains the token only through loopback `/local/session`.
- Electron does not expose Node.js APIs to the renderer.
- The wrapper reuses a healthy `hapa-drama` server when one is already running on the selected port.
- If no server is running, Electron starts `python -m hapa_drama_node.cli serve` with `PYTHONPATH=python`.
- Python must be `>=3.11` to avoid stale Python 3.9 server behavior.
- Runtime state is written to `artifacts/runtime/hapa_drama_runtime.json`.

## Build

```bash
scripts/launch_hapa_drama.sh --build
```

This creates `.venv`, installs the Python package editable, and installs local Electron dependencies.

## Launch desktop

```bash
scripts/launch_hapa_drama.sh --electron
```

Or double-click one of:

- `$HOME/Desktop/Hapa Drama.app`
- `launch_hapa_drama_desktop.command`
- `$HOME/Desktop/Launch Hapa Drama.command`

Install or refresh the native `.app` launcher:

```bash
scripts/install_desktop_launcher.sh
```

The desktop launcher uses port `8758` unless `HAPA_DRAMA_PORT` is set.

## Watch mode

```bash
scripts/launch_hapa_drama.sh --watch
```

Watch mode sets `HAPA_DRAMA_ELECTRON_DEV=1`. If Electron starts the backend, it starts FastAPI with `--reload` and opens detached DevTools. If a healthy server is already running on the selected port, Electron reuses it.

## Browser fallback

```bash
scripts/launch_hapa_drama.sh --open
```

## Doctor

```bash
scripts/launch_hapa_drama.sh --doctor
```

Doctor checks Python, Node, npm, Electron deps, token/runtime paths, and current `/health` status.
