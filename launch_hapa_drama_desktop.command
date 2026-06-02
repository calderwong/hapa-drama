#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
export HAPA_DRAMA_HOST="${HAPA_DRAMA_HOST:-127.0.0.1}"
export HAPA_DRAMA_PORT="${HAPA_DRAMA_PORT:-8758}"

if [ ! -x "$ROOT_DIR/node_modules/.bin/electron" ]; then
  echo "Hapa Drama Electron dependencies are not installed yet."
  echo "Running build now; this installs the local Python package and Electron dependencies."
  "$ROOT_DIR/scripts/launch_hapa_drama.sh" --build
fi

"$ROOT_DIR/scripts/launch_hapa_drama.sh" --electron
