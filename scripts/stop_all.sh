#!/bin/bash
# Stop LiveKit SFU server and backend
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Kill LiveKit
if [ -f "$PROJECT_DIR/.livekit.pid" ]; then
  PID=$(cat "$PROJECT_DIR/.livekit.pid")
  kill "$PID" 2>/dev/null || true
  rm -f "$PROJECT_DIR/.livekit.pid"
  echo "LiveKit stopped (PID: $PID)"
fi

# Kill uvicorn
kill $(lsof -ti:8000 2>/dev/null) 2>/dev/null || true
echo "Backend stopped"

echo "All services down."