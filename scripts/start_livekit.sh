#!/bin/bash
# Start LiveKit SFU server directly (no Docker needed)
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
"$PROJECT_DIR/livekit-server.exe" --config "$PROJECT_DIR/config/livekit.yaml" &
LIVEKIT_PID=$!
echo "LiveKit server starting (PID: $LIVEKIT_PID) on ports 7880-7882"
echo "$LIVEKIT_PID" > "$PROJECT_DIR/.livekit.pid"
