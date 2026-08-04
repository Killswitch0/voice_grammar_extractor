#!/usr/bin/env bash
# One-command entry point (macOS/Linux). Builds the image on first use, then
# just runs it. Everything after the script name is passed straight to main.py.
#
# Examples:
#   ./run.sh call.webm --reference my_voice.wav
#   ./run.sh monologue.mp4 --no-diarization
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

if [ ! -f .env ]; then
  cp .env.example .env
fi

exec docker compose run --rm extractor "$@"
