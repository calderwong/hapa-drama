#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

python_bin() {
  if command -v python3.11 >/dev/null 2>&1; then
    command -v python3.11
  elif command -v python3 >/dev/null 2>&1; then
    command -v python3
  else
    echo "python3.11 or python3 is required" >&2
    exit 1
  fi
}

clone_or_update() {
  local url="$1"
  local dest="$2"
  if [ -d "$dest/.git" ]; then
    echo "[optional-engines] using existing $dest"
  else
    mkdir -p "$(dirname "$dest")"
    git clone --depth 1 "$url" "$dest"
  fi
}

install_chatterbox() {
  local py
  py="$(python_bin)"
  clone_or_update "https://github.com/resemble-ai/chatterbox.git" "$ROOT_DIR/upstream/chatterbox"
  if [ ! -x "$ROOT_DIR/upstream/chatterbox/.venv/bin/python" ]; then
    "$py" -m venv "$ROOT_DIR/upstream/chatterbox/.venv"
  fi
  "$ROOT_DIR/upstream/chatterbox/.venv/bin/python" -m pip install --upgrade pip setuptools wheel
  "$ROOT_DIR/upstream/chatterbox/.venv/bin/pip" install -e "$ROOT_DIR/upstream/chatterbox"
}

install_dramabox() {
  local py
  py="$(python_bin)"
  clone_or_update "https://github.com/resemble-ai/DramaBox.git" "$ROOT_DIR/upstream/DramaBox"
  if [ ! -x "$ROOT_DIR/upstream/DramaBox/.venv/bin/python" ]; then
    "$py" -m venv "$ROOT_DIR/upstream/DramaBox/.venv"
  fi
  "$ROOT_DIR/upstream/DramaBox/.venv/bin/python" -m pip install --upgrade pip setuptools wheel
  "$ROOT_DIR/upstream/DramaBox/.venv/bin/pip" install -r "$ROOT_DIR/upstream/DramaBox/requirements.txt"
}

install_mlx_audio() {
  local py
  py="$(python_bin)"
  clone_or_update "https://github.com/Blaizzy/mlx-audio.git" "$ROOT_DIR/upstream/mlx-audio"
  if [ ! -x "$ROOT_DIR/upstream/mlx-audio/.venv/bin/python" ]; then
    "$py" -m venv "$ROOT_DIR/upstream/mlx-audio/.venv"
  fi
  "$ROOT_DIR/upstream/mlx-audio/.venv/bin/python" -m pip install --upgrade pip setuptools wheel
  "$ROOT_DIR/upstream/mlx-audio/.venv/bin/pip" install -e "$ROOT_DIR/upstream/mlx-audio[tts]"
}

case "${1:-all}" in
  all)
    install_chatterbox
    install_dramabox
    install_mlx_audio
    ;;
  chatterbox)
    install_chatterbox
    ;;
  dramabox)
    install_dramabox
    ;;
  mlx-audio|mlx-dramabox|dramabox-mlx)
    install_mlx_audio
    ;;
  *)
    echo "Usage: scripts/install_optional_engines.sh [all|chatterbox|dramabox|mlx-audio|mlx-dramabox]" >&2
    exit 1
    ;;
esac

echo "[optional-engines] done"
