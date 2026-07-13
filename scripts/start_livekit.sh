#!/bin/bash
# Start a local LiveKit server binary using credentials from .env.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$PROJECT_DIR/.env"
SERVER_BIN="$PROJECT_DIR/livekit-server.exe"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE. Copy .env.example to .env and configure it first." >&2
  exit 1
fi

if [[ ! -x "$SERVER_BIN" ]]; then
  echo "Missing executable LiveKit server at $SERVER_BIN." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

: "${LIVEKIT_API_KEY:?LIVEKIT_API_KEY must be configured in .env}"
: "${LIVEKIT_API_SECRET:?LIVEKIT_API_SECRET must be configured in .env}"

"$SERVER_BIN" \
  --config "$PROJECT_DIR/config/livekit.yaml" \
  --keys "${LIVEKIT_API_KEY}: ${LIVEKIT_API_SECRET}" &
LIVEKIT_PID=$!

echo "LiveKit server starting (PID: $LIVEKIT_PID) on ports 7880-7882"
echo "$LIVEKIT_PID" > "$PROJECT_DIR/.livekit.pid"
