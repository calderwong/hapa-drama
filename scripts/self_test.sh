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
hapa-drama self-test --token "$TOKEN"
