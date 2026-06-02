#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEFAULT_HOST="${HAPA_DRAMA_HOST:-127.0.0.1}"
DEFAULT_PORT="${HAPA_DRAMA_PORT:-8758}"
DEFAULT_URL="http://${DEFAULT_HOST}:${DEFAULT_PORT}"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

usage() {
  cat <<'EOF'
Usage: scripts/launch_hapa_drama.sh [--doctor|--build|--run|--electron|--watch|--self-test|--open]

  --doctor     Validate local prerequisites, runtime paths, and desktop wrapper state
  --build      Create Python venv, install Python package, and install Electron deps
  --run        Start the node server in the foreground on HAPA_DRAMA_PORT or 8758
  --electron   Launch the Electron desktop wrapper
  --watch      Launch Electron in dev mode; backend starts with --reload if Electron owns it
  --self-test  Run the node self-test against HAPA_DRAMA_PORT or 8758
  --open       Open the browser UI at HAPA_DRAMA_PORT or 8758
EOF
}

python_is_compatible() {
  "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1
}

python_bin() {
  local candidates=()
  if [ -n "${HAPA_DRAMA_PYTHON:-}" ]; then
    candidates+=("$HAPA_DRAMA_PYTHON")
  fi
  candidates+=("$ROOT_DIR/.venv/bin/python")
  if command -v python3.11 >/dev/null 2>&1; then
    candidates+=("$(command -v python3.11)")
  fi
  if command -v python3 >/dev/null 2>&1; then
    candidates+=("$(command -v python3)")
  fi
  for candidate in "${candidates[@]}"; do
    if [ -x "$candidate" ] && python_is_compatible "$candidate"; then
      echo "$candidate"
      return 0
    elif command -v "$candidate" >/dev/null 2>&1; then
      resolved="$(command -v "$candidate")"
      if python_is_compatible "$resolved"; then
        echo "$resolved"
        return 0
      fi
    fi
  done
  echo "Missing compatible Python >=3.11" >&2
  exit 1
}

export_runtime_env() {
  export HAPA_DRAMA_HOST="${HAPA_DRAMA_HOST:-$DEFAULT_HOST}"
  export HAPA_DRAMA_PORT="${HAPA_DRAMA_PORT:-$DEFAULT_PORT}"
  export HAPA_DRAMA_RUNTIME_FILE="${HAPA_DRAMA_RUNTIME_FILE:-$ROOT_DIR/artifacts/runtime/hapa_drama_runtime.json}"
  export PYTHONPATH="$ROOT_DIR/python${PYTHONPATH:+:$PYTHONPATH}"
  export HAPA_DRAMA_DEFAULT_MODE="${HAPA_DRAMA_DEFAULT_MODE:-drama}"
  export HAPA_DRAMA_DEFAULT_TTS_ENGINE="${HAPA_DRAMA_DEFAULT_TTS_ENGINE:-dramabox}"
  export HAPA_DRAMA_DEFAULT_VOICE_PROFILE_ID="${HAPA_DRAMA_DEFAULT_VOICE_PROFILE_ID:-profile-operator-default}"
  export HAPA_DRAMA_DEFAULT_VOICE_ID="${HAPA_DRAMA_DEFAULT_VOICE_ID:-voice-operator-default}"
  export HAPA_DRAMA_DEFAULT_VOICE_DISPLAY_NAME="${HAPA_DRAMA_DEFAULT_VOICE_DISPLAY_NAME:-Operator Default Voice}"
  if [ -z "${HAPA_DRAMA_DEFAULT_VOICE_CLIP_PATH:-}" ]; then
    local default_voice_wav="$ROOT_DIR/data/default_voice/operator-default-reference.wav"
    if [ -f "$default_voice_wav" ]; then
      export HAPA_DRAMA_DEFAULT_VOICE_CLIP_PATH="$default_voice_wav"
    fi
  fi
  if [ -z "${HAPA_DRAMA_ENABLE_MLX_AUDIO:-}" ]; then
    local mlx_candidates=(
      "$HOME/pinokio/drive/drives/pip/mlx-audio/0.2.7/bin/mlx_audio.tts.generate"
      "$HOME/pinokio/drive/drives/pip/mlx-audio/0.2.6/bin/mlx_audio.tts.generate"
    )
    local candidate
    for candidate in "${mlx_candidates[@]}"; do
      if [ -x "$candidate" ]; then
        export HAPA_DRAMA_ENABLE_MLX_AUDIO=1
        export HAPA_DRAMA_MLX_AUDIO_CLI="${HAPA_DRAMA_MLX_AUDIO_CLI:-$candidate}"
        export HAPA_DRAMA_MLX_AUDIO_MODEL="${HAPA_DRAMA_MLX_AUDIO_MODEL:-mlx-community/IndexTTS}"
        break
      fi
    done
  fi
  if [ -z "${HAPA_DRAMA_ENABLE_MLX_DRAMABOX:-}" ]; then
    local mlx_dramabox_cli="$ROOT_DIR/upstream/mlx-audio/.venv/bin/mlx_audio.tts.generate"
    if [ -x "$mlx_dramabox_cli" ]; then
      export HAPA_DRAMA_ENABLE_MLX_DRAMABOX=1
      export HAPA_DRAMA_MLX_DRAMABOX_CLI="${HAPA_DRAMA_MLX_DRAMABOX_CLI:-$mlx_dramabox_cli}"
      export HAPA_DRAMA_MLX_DRAMABOX_MODEL="${HAPA_DRAMA_MLX_DRAMABOX_MODEL:-mlx-community/ResembleAI-Dramabox}"
      export HAPA_DRAMA_MLX_DRAMABOX_TIMEOUT_SECONDS="${HAPA_DRAMA_MLX_DRAMABOX_TIMEOUT_SECONDS:-1200}"
      export HAPA_DRAMA_MLX_DRAMABOX_CFG_SCALE="${HAPA_DRAMA_MLX_DRAMABOX_CFG_SCALE:-6.0}"
    fi
  fi
  if [ -z "${HAPA_DRAMA_ENABLE_CHATTERBOX:-}" ]; then
    local chatterbox_python="$ROOT_DIR/upstream/chatterbox/.venv/bin/python"
    if [ -x "$chatterbox_python" ]; then
      export HAPA_DRAMA_ENABLE_CHATTERBOX=1
      export HAPA_DRAMA_CHATTERBOX_PYTHON="${HAPA_DRAMA_CHATTERBOX_PYTHON:-$chatterbox_python}"
      export HAPA_DRAMA_CHATTERBOX_ROOT="${HAPA_DRAMA_CHATTERBOX_ROOT:-$ROOT_DIR/upstream/chatterbox}"
      export HAPA_DRAMA_CHATTERBOX_MODEL="${HAPA_DRAMA_CHATTERBOX_MODEL:-standard}"
    fi
  fi
  if [ -z "${HAPA_DRAMA_DRAMABOX_ROOT:-}" ] && [ -f "$ROOT_DIR/upstream/DramaBox/src/inference.py" ]; then
    export HAPA_DRAMA_DRAMABOX_ROOT="$ROOT_DIR/upstream/DramaBox"
  fi
  if [ -z "${HAPA_DRAMA_DRAMABOX_PYTHON:-}" ] && [ -x "$ROOT_DIR/upstream/DramaBox/.venv/bin/python" ]; then
    export HAPA_DRAMA_DRAMABOX_PYTHON="$ROOT_DIR/upstream/DramaBox/.venv/bin/python"
  fi
  if [ -z "${HAPA_DRAMA_ENABLE_DRAMABOX:-}" ] && [ -x "$ROOT_DIR/upstream/DramaBox/.venv/bin/python" ]; then
    export HAPA_DRAMA_ENABLE_DRAMABOX=1
  fi
}

doctor() {
  echo "[doctor] root: $ROOT_DIR"
  PYTHON_BIN="$(python_bin)"
  echo "[doctor] python: $PYTHON_BIN"
  if [ -f "$ROOT_DIR/.node_token" ]; then
    echo "[doctor] token file: OK"
  else
    echo "[doctor] token file not yet generated (created at first boot/build import)"
  fi
  if command -v node >/dev/null 2>&1; then
    echo "[doctor] node: $(node --version)"
  else
    echo "[doctor] node: missing (required for Electron desktop wrapper)"
  fi
  if command -v npm >/dev/null 2>&1; then
    echo "[doctor] npm: $(npm --version)"
  else
    echo "[doctor] npm: missing (required for Electron desktop wrapper)"
  fi
  if command -v say >/dev/null 2>&1 && command -v afconvert >/dev/null 2>&1; then
    echo "[doctor] macOS speech: OK"
  else
    echo "[doctor] macOS speech: unavailable (will use other enabled engines or stub fallback)"
  fi
  export_runtime_env
  if [ "${HAPA_DRAMA_ENABLE_MLX_AUDIO:-0}" = "1" ]; then
    echo "[doctor] MLX-Audio: enabled via ${HAPA_DRAMA_MLX_AUDIO_CLI:-PATH}"
    echo "[doctor] MLX model: ${HAPA_DRAMA_MLX_AUDIO_MODEL:-mlx-community/IndexTTS}"
  else
    echo "[doctor] MLX-Audio: disabled"
  fi
  local saved_default_route_file="${HAPA_DRAMA_DEFAULT_ROUTE_FILE:-$ROOT_DIR/data/default_route.json}"
  if [ -f "$saved_default_route_file" ]; then
    local saved_default_route
    saved_default_route="$("$PYTHON_BIN" -c 'import json, sys
route=json.load(open(sys.argv[1]))
print("{} / {} / {}".format(route.get("mode") or "auto", route.get("tts_engine") or "auto", route.get("voice_profile_id") or "no-profile"))
print(route.get("voice_clip_path") or "")
' "$saved_default_route_file" 2>/dev/null || true)"
    if [ -n "$saved_default_route" ]; then
      echo "[doctor] Saved default route: $(printf '%s\n' "$saved_default_route" | sed -n '1p')"
      local saved_default_clip
      saved_default_clip="$(printf '%s\n' "$saved_default_route" | sed -n '2p')"
      if [ -n "$saved_default_clip" ]; then
        echo "[doctor] Saved default voice clip: $saved_default_clip"
      fi
    fi
  elif [ -n "${HAPA_DRAMA_DEFAULT_VOICE_CLIP_PATH:-}" ]; then
    echo "[doctor] Default route: ${HAPA_DRAMA_DEFAULT_MODE:-drama} / ${HAPA_DRAMA_DEFAULT_TTS_ENGINE:-dramabox} / ${HAPA_DRAMA_DEFAULT_VOICE_PROFILE_ID:-profile-operator-default}"
    echo "[doctor] Default voice clip: ${HAPA_DRAMA_DEFAULT_VOICE_CLIP_PATH}"
  else
    echo "[doctor] Default voice clip: missing"
  fi
  if [ "${HAPA_DRAMA_ENABLE_MLX_DRAMABOX:-0}" = "1" ]; then
    echo "[doctor] DramaBox MLX: enabled via ${HAPA_DRAMA_MLX_DRAMABOX_CLI:-PATH}"
    echo "[doctor] DramaBox MLX model: ${HAPA_DRAMA_MLX_DRAMABOX_MODEL:-mlx-community/ResembleAI-Dramabox}"
  else
    echo "[doctor] DramaBox MLX: disabled"
  fi
  if [ "${HAPA_DRAMA_ENABLE_CHATTERBOX:-0}" = "1" ]; then
    echo "[doctor] Chatterbox: enabled via ${HAPA_DRAMA_CHATTERBOX_PYTHON:-PATH}"
    echo "[doctor] Chatterbox root: ${HAPA_DRAMA_CHATTERBOX_ROOT:-auto}"
  else
    echo "[doctor] Chatterbox: disabled"
  fi
  if [ "${HAPA_DRAMA_ENABLE_DRAMABOX:-0}" = "1" ]; then
    echo "[doctor] DramaBox: enabled via ${HAPA_DRAMA_DRAMABOX_ROOT:-auto}"
  else
    echo "[doctor] DramaBox: disabled (set HAPA_DRAMA_ENABLE_DRAMABOX=1 to expose the CUDA-heavy backend)"
  fi
  if [ -x "$ROOT_DIR/node_modules/.bin/electron" ]; then
    echo "[doctor] electron deps: OK"
  else
    echo "[doctor] electron deps: missing (run --build)"
  fi
  echo "[doctor] default URL: $DEFAULT_URL"
  "$PYTHON_BIN" - <<PY
import json, urllib.request
url = "${DEFAULT_URL}/health"
try:
    with urllib.request.urlopen(url, timeout=1) as res:
        payload = json.loads(res.read().decode("utf-8"))
    print(f"[doctor] health: {payload.get('service')} ok={payload.get('ok')} url=${DEFAULT_URL}")
except Exception as exc:
    print(f"[doctor] health: offline at ${DEFAULT_URL} ({exc})")
PY
  echo "[doctor] done"
}

build() {
  cd "$ROOT_DIR"
  PYTHON_BIN="$(python_bin)"
  if [ ! -d .venv ]; then
    "$PYTHON_BIN" -m venv .venv
  fi
  source .venv/bin/activate
  python -m pip install --upgrade pip
  python -m pip install -e .
  if command -v npm >/dev/null 2>&1; then
    npm install
  else
    echo "npm is required for the Electron wrapper; install Node.js/npm and rerun --build" >&2
    exit 1
  fi
}

run_node() {
  cd "$ROOT_DIR"
  export_runtime_env
  PYTHON_BIN="$(python_bin)"
  "$PYTHON_BIN" -m hapa_drama_node.cli serve --host "$HAPA_DRAMA_HOST" --port "$HAPA_DRAMA_PORT"
}

self_test() {
  cd "$ROOT_DIR"
  export_runtime_env
  PYTHON_BIN="$(python_bin)"
  TOKEN="$(cat .node_token)"
  "$PYTHON_BIN" -m hapa_drama_node.cli self-test --base-url "http://${HAPA_DRAMA_HOST}:${HAPA_DRAMA_PORT}" --token "$TOKEN"
}

require_electron_deps() {
  if [ ! -x "$ROOT_DIR/node_modules/.bin/electron" ]; then
    echo "Electron deps are missing. Run: scripts/launch_hapa_drama.sh --build" >&2
    exit 1
  fi
}

run_electron() {
  cd "$ROOT_DIR"
  export_runtime_env
  require_electron_deps
  npm run desktop
}

watch() {
  cd "$ROOT_DIR"
  export_runtime_env
  export HAPA_DRAMA_ELECTRON_DEV=1
  require_electron_deps
  npm run watch
}

open_ui() {
  export_runtime_env
  open "http://${HAPA_DRAMA_HOST}:${HAPA_DRAMA_PORT}"
}

case "${1:-}" in
  --doctor)
    doctor
    ;;
  --build)
    build
    ;;
  --run)
    run_node
    ;;
  --electron)
    run_electron
    ;;
  --watch)
    watch
    ;;
  --self-test)
    self_test
    ;;
  --open)
    open_ui
    ;;
  *)
    usage
    exit 1
    ;;
esac
