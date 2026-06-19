import pytest
from pathlib import Path
import tempfile
import os
import json
from backend.orchestrator.transcript_log import TranscriptLog


@pytest.mark.asyncio
async def test_log_writes_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        log = TranscriptLog(Path(tmpdir))
        await log.log_exchange(1, "examiner", "Did you see the accused?")
        await log.log_exchange(2, "witness", "I don't recall")
        lines = open(Path(tmpdir) / "transcript.jsonl").readlines()
        assert len(lines) == 2


@pytest.mark.asyncio
async def test_log_entries_have_correct_structure():
    with tempfile.TemporaryDirectory() as tmpdir:
        log = TranscriptLog(Path(tmpdir))
        await log.log_exchange(1, "examiner", "Where were you?", {"exhibit": "E1"})
        lines = open(Path(tmpdir) / "transcript.jsonl").readlines()
        entry = json.loads(lines[0])
        assert entry["turn"] == 1
        assert entry["speaker"] == "examiner"
        assert entry["text"] == "Where were you?"
        assert entry["metadata"]["exhibit"] == "E1"
        assert "timestamp" in entry


@pytest.mark.asyncio
async def test_log_creates_directory():
    with tempfile.TemporaryDirectory() as tmpdir:
        nested = Path(tmpdir) / "subdir" / "logs"
        log = TranscriptLog(nested)
        await log.log_exchange(1, "witness", "I saw nothing")
        assert nested.exists()
        assert (nested / "transcript.jsonl").exists()
