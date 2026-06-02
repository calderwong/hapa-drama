#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
if [ -f .venv/bin/activate ]; then
  source .venv/bin/activate
fi
TOKEN="${HAPA_DRAMA_TOKEN:-}"
if [ -z "$TOKEN" ] && [ -f .node_token ]; then
  TOKEN="$(cat .node_token)"
fi
START_NS="$(python - <<'PY'
import time
print(time.monotonic_ns())
PY
)"
hapa-drama synthesize --token "$TOKEN" --mode flow --text "Latency smoke." >/tmp/hapa_drama_latency_smoke.json
END_NS="$(python - <<'PY'
import time
print(time.monotonic_ns())
PY
)"
python - <<PY
elapsed = ($END_NS - $START_NS) / 1_000_000_000
print(f"latency_seconds={elapsed:.3f}")
raise SystemExit(0 if elapsed < 5 else 1)
PY
