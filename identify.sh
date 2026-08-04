#!/usr/bin/env bash
# One-command entry point for the voice-picking helper (macOS/Linux).
#
# Example:
#   ./identify.sh call.webm -o output
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

if [ ! -f .env ]; then
  cp .env.example .env
fi

exec docker compose run --rm identify "$@"
