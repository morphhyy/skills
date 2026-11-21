#!/usr/bin/env bash
# Installs everything the live clipper needs (macOS/Homebrew or Linux w/ pipx/uv).
set -euo pipefail
have() { command -v "$1" >/dev/null 2>&1; }

if have brew; then
  for pkg in ffmpeg streamlink whisper-cpp uv; do
    bin=$pkg; [ "$pkg" = whisper-cpp ] && bin=whisper-cli
    have "$bin" || brew install "$pkg"
  done
else
  have ffmpeg || { echo "install ffmpeg with your package manager"; exit 1; }
  have uv || curl -LsSf https://astral.sh/uv/install.sh | sh
  have streamlink || uv tool install streamlink
  have whisper-cli || echo "! build whisper.cpp (github.com/ggml-org/whisper.cpp) for captions"
fi

MODEL="${WHISPER_MODEL:-small}"   # tiny | base | small | medium | large-v3-turbo
DEST="$HOME/.cache/whisper/ggml-$MODEL.bin"
if [ ! -f "$DEST" ]; then
  mkdir -p "$(dirname "$DEST")"
  curl -L --fail -o "$DEST" "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-$MODEL.bin"
fi

mkdir -p "$HOME/.config/live-clipper"
echo "OK  streamlink: $(streamlink --version 2>/dev/null)"
echo "OK  ffmpeg:     $(ffmpeg -version | head -1)"
echo "OK  whisper:    $DEST"
[ -f "$HOME/.config/live-clipper/client_secret.json" ] \
  && echo "OK  YouTube client secret present" \
  || echo "--  YouTube upload not set up yet (see SKILL.md 'YouTube setup')"
