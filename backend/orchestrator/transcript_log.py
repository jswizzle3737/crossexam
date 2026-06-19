"""Real-time parallel transcript log — every exchange logged via JSONL."""

import json
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class TranscriptLog:
    def __init__(self, session_dir: Path):
        self.session_dir = session_dir
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self._log_path = session_dir / "transcript.jsonl"
        self._lock = asyncio.Lock()

    async def log_exchange(self, turn_number: int, speaker: str, text: str, metadata: Optional[dict] = None):
        entry = {
            "turn": turn_number,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "speaker": speaker,
            "text": text,
            "metadata": metadata or {},
        }
        async with self._lock:
            with open(self._log_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
