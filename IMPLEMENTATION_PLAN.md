# Adversarial Witness Cross-Examination Trainer — Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Build a real-time, bidirectional voice-to-voice cross-examination training platform that democratizes courtroom prep — giving witnesses the same rigorous adversarial practice as principal defendants.

**Architecture:** WebRTC pipeline (LiveKit SFU) + semantic VAD barge-in + multi-agent criminal LLM orchestrator. Sub-500ms voice round-trip. Post-session scorecard with targeted replay loops.

**Tech Stack:** LiveKit (SFU/WebRTC), Cartesia Sonic-3 / ElevenLabs Flash (TTS), custom VAD barge-in module, Python + FastAPI (orchestration), SQLite/PostgreSQL (session store), WebSocket text log.

---

## Phase 0: Project Foundation

### Task 0.1: Scaffold project structure

**Objective:** Create the directory tree, venv, and dependency lock.

**Files:**
- Create: `witness-prep/`
  - `backend/`
    - `orchestrator/`
    - `vad_engine/`
    - `llm_agent/`
    - `scorecard/`
    - `replay/`
  - `frontend/`
    - `public/`
    - `src/`
  - `config/`
    - `profiles/`
  - `tests/`
  - `docker/`
  - `scripts/`

**Step 1: Create directories**

Run:
```bash
cd ~/Desktop/witness-prep
mkdir -p backend/{orchestrator,vad_engine,llm_agent,scorecard,replay}
mkdir -p frontend/{public,src}
mkdir -p config/profiles tests docker scripts
```

**Step 2: Initialize Python venv + requirements**

Create `requirements.txt` with:
```
fastapi==0.115.0
uvicorn[standard]==0.30.0
livekit-api>=1.6.0
websockets>=12.0
pydantic>=2.8.0
sqlalchemy>=2.0.30
httpx>=0.27.0
python-dotenv>=1.0.0
```

Run:
```bash
cd ~/Desktop/witness-prep
python -m venv .venv
source .venv/bin/activate  # or .venv/Scripts/activate on Windows
pip install -r requirements.txt
```

---

## Phase 1: WebRTC Streaming Pipeline

### Task 1.1: LiveKit SFU bootstrap

**Objective:** Stand up a LiveKit server instance and establish a basic WebRTC connection from the browser client.

**Files:**
- Create: `docker/docker-compose.yml` (LiveKit + Redis)
- Create: `config/livekit.yaml`
- Create: `scripts/start_livekit.sh`
- Modify: `frontend/src/index.html`

**Step 1: Write docker-compose**

Create `docker/docker-compose.yml`:
```yaml
version: "3.9"
services:
  livekit:
    image: livekit/livekit-server:latest
    command: --config /etc/livekit.yaml
    ports:
      - "7880:7880"   # HTTP
      - "7881:7881"   # WebRTC UDP
      - "7882:7882"   # TURN TCP
    volumes:
      - ../config/livekit.yaml:/etc/livekit.yaml
    restart: unless-stopped
```

**Step 2: Write LiveKit config**

Create `config/livekit.yaml`:
```yaml
port: 7880
bind_addresses:
  - "0.0.0.0"
rtc:
  port_range_start: 7881
  port_range_end: 7882
  udp_port: 7881
  use_external_ip: false
  stun_servers:
    - "stun.l.google.com:19302"
keys:
  devkey: "secretdevkey123"
logging:
  level: info
```

**Step 3: Write start script**

Create `scripts/start_livekit.sh`:
```bash
#!/bin/bash
set -euo pipefail
docker compose -f docker/docker-compose.yml up -d livekit
echo "LiveKit running on ports 7880-7882"
```

**Step 4: Verify WebRTC connection**

Run: `bash scripts/start_livekit.sh`
Expected: Docker container starts, LiveKit logs show "Starting LiveKit Server"

---

### Task 1.2: WebRTC gateway module (Python)

**Objective:** Python module that connects to LiveKit, manages participant rooms, and streams audio tracks.

**Files:**
- Create: `backend/orchestrator/webrtc_gateway.py`
- Create: `tests/test_webrtc_gateway.py`

**Step 1: Write gateway module**

Create `backend/orchestrator/webrtc_gateway.py` — NOTE: `livekit-api>=1.0.0` uses protobuf request objects:

```python
"""WebRTC gateway — manages LiveKit room lifecycle and participant audio streams."""

import asyncio
from dataclasses import dataclass
from livekit import api
from livekit.protocol.room import CreateRoomRequest


@dataclass
class RoomConfig:
    name: str
    max_participants: int = 2
    empty_timeout: int = 300  # 5 minutes


class WebRTCGateway:
    def __init__(self, host: str = "localhost", port: int = 7880, api_key: str = "devkey", api_secret: str = "secretdevkey123"):
        url = f"http://{host}:{port}"
        self._client = api.LiveKitAPI(url=url, api_key=api_key, api_secret=api_secret)

    async def create_room(self, config: RoomConfig) -> str:
        """Create a WebRTC room and return its name."""
        req = CreateRoomRequest(
            name=config.name,
            max_participants=config.max_participants,
            empty_timeout=config.empty_timeout,
        )
        room = await self._client.room.create_room(req)
        return room.name

    async def generate_token(self, room_name: str, identity: str) -> str:
        """Generate an access token for a participant."""
        token = api.AccessToken(api_key="devkey", api_secret="secretdevkey123") \
            .with_identity(identity) \
            .with_grants(api.VideoGrants(room_join=True, room=room_name))
        return token.to_jwt()

    async def close(self):
        await self._client.aclose()
```

**Step 2: Write test**

Create `tests/test_webrtc_gateway.py`:
```python
import pytest
from backend.orchestrator.webrtc_gateway import WebRTCGateway, RoomConfig

@pytest.mark.asyncio
async def test_gateway_creates_room():
    gw = WebRTCGateway()
    room_name = await gw.create_room(RoomConfig(name="test-trial-1"))
    assert room_name == "test-trial-1"
    await gw.close()
```

**Step 3: Run test**

Run: `pytest tests/test_webrtc_gateway.py -v`
Expected: PASS (requires LiveKit container running)

---

## Phase 2: VAD & Barge-In Layer

### Task 2.1: Client-side VAD module

**Objective:** Real-time Voice Activity Detection in the browser using Silero VAD or a WebAssembly-compiled VAD model. Detects when the user speaks (barge-in) and fires an interrupt signal over the WebRTC data channel.

**Files:**
- Create: `frontend/src/vad.js`
- Create: `frontend/src/vad_worker.js` (Web Worker for off-thread VAD)

**Step 1: Write VAD worker**

Create `frontend/src/vad_worker.js`:
```javascript
// VAD Web Worker — runs Silero-lite inference off the main thread
// Receives Float32Array audio chunks, returns VAD state changes

let vadState = false; // false = silence, true = speech

self.onmessage = async (event) => {
  const { audioBuffer, sampleRate } = event.data;

  // Silero-lite inference would go here via ONNX runtime WASM
  // For MVP: energy-threshold VAD
  const energy = audioBuffer.reduce((sum, s) => sum + Math.abs(s), 0) / audioBuffer.length;
  const threshold = 0.02; // tunable
  const isSpeech = energy > threshold;

  if (isSpeech !== vadState) {
    vadState = isSpeech;
    self.postMessage({ type: 'vad_change', speaking: isSpeech, energy });
  }
};
```

**Step 2: Write VAD manager**

Create `frontend/src/vad.js`:
```javascript
/**
 * VAD Manager — connects microphone stream to Web Worker, emits events.
 */
export class VADManager {
  constructor(dataChannel) {
    this.dataChannel = dataChannel;
    this.worker = new Worker('./vad_worker.js');
    this.listening = false;

    this.worker.onmessage = (event) => {
      if (event.data.type === 'vad_change' && event.data.speaking) {
        // Barge-in detected — send interrupt signal over data channel
        if (this.dataChannel?.readyState === 'open') {
          this.dataChannel.send(JSON.stringify({ type: 'interrupt' }));
        }
      }
    };
  }

  async start(stream) {
    const audioContext = new AudioContext();
    const source = audioContext.createMediaStreamSource(stream);
    const processor = audioContext.createScriptProcessor(4096, 1, 1);

    processor.onaudioprocess = (event) => {
      if (!this.listening) return;
      const input = event.inputBuffer.getChannelData(0);
      this.worker.postMessage({ audioBuffer: input, sampleRate: audioContext.sampleRate });
    };

    source.connect(processor);
    processor.connect(audioContext.destination);
    this.listening = true;
  }

  stop() {
    this.listening = false;
  }
}
```

---

### Task 2.2: Semantic turn detection (backend)

**Objective:** Analyze completed-utterance semantics rather than raw silence timers — distinguishing a witness pausing to think from finishing their answer.

**Files:**
- Create: `backend/vad_engine/semantic_turn.py`
- Create: `tests/test_semantic_turn.py`

**Step 1: Write semantic turn detector**

Create `backend/vad_engine/semantic_turn.py`:
```python
"""Semantic turn detection — analyzes utterance completeness via cadence + sentence structure."""

import re
from dataclasses import dataclass, field

@dataclass
class UtteranceFeatures:
    word_count: int = 0
    ends_with_question: bool = False
    ends_with_conjunction: bool = False
    has_trailing_filler: bool = False
    pause_after_ms: float = 0.0

class SemanticTurnDetector:
    FILLER_WORDS = {"uh", "um", "like", "you know", "i mean", "well", "actually", "basically", "literally", "right?", "see", "look", "listen"}
    TRAILING_CONJUNCTIONS = {"and", "but", "or", "so", "because", "however"}

    def is_turn_complete(self, transcript: str, pause_ms: float) -> bool:
        """Determine if the user has finished their turn."""
        features = self._extract_features(transcript, pause_ms)
        return self._classify(features)

    def _extract_features(self, transcript: str, pause_ms: float) -> UtteranceFeatures:
        text = transcript.strip().lower()
        words = text.split()
        features = UtteranceFeatures(
            word_count=len(words),
            ends_with_question=text.endswith("?"),
            ends_with_conjunction=words[-1] in self.TRAILING_CONJUNCTIONS if words else False,
            has_trailing_filler=self._has_trailing_filler(text),
            pause_after_ms=pause_ms,
        )
        return features

    def _has_trailing_filler(self, text: str) -> bool:
        last_word = text.split()[-1] if text.split() else ""
        return last_word.rstrip(".,!?").lower() in self.FILLER_WORDS

    def _classify(self, features: UtteranceFeatures) -> bool:
        # Complete if: question mark, or silence > 1.2s with no trailing conjunction/filler
        if features.ends_with_question:
            return True
        if features.ends_with_conjunction:
            return False  # Pausing at "and" or "but" — more coming
        if features.has_trailing_filler:
            return False  # Verbal pause — witness is stalling, not done
        if features.pause_after_ms > 1200:
            return True   # Silence long enough to signal completion
        return False
```

**Step 2: Write tests**

Create `tests/test_semantic_turn.py`:
```python
import pytest
from backend.vad_engine.semantic_turn import SemanticTurnDetector

@pytest.fixture
def detector():
    return SemanticTurnDetector()

def test_question_is_complete(detector):
    assert detector.is_turn_complete("What did you see?", 200) == True

def test_conjunction_pause_not_complete(detector):
    assert detector.is_turn_complete("I saw him and", 800) == False

def test_filler_not_complete(detector):
    assert detector.is_turn_complete("Well, I uh", 500) == False

def test_long_silence_is_complete(detector):
    assert detector.is_turn_complete("I saw the car", 1500) == True

def test_short_pause_not_complete(detector):
    assert detector.is_turn_complete("I saw the car", 400) == False
```

**Step 3: Run tests**

Run: `pytest tests/test_semantic_turn.py -v`
Expected: 5 passed

---

## Phase 3: Multi-Agent Criminal LLM

### Task 3.1: Adversarial examiner agent

**Objective:** LLM agent that adopts a Crown prosecutor persona — confrontational, leading-question heavy, bound by Canadian criminal procedure.

**Files:**
- Create: `backend/llm_agent/examiner.py`
- Create: `backend/llm_agent/prompts/examiner_system.txt`
- Create: `tests/test_examiner.py`

**Step 1: Write examiner prompt**

Create `backend/llm_agent/prompts/examiner_system.txt`:
```text
You are a Crown prosecutor conducting a rigorous cross-examination in an Ontario Superior Court trial.

Style:
- Formal, high-assertiveness, rhythmic pacing
- Lead with yes/no questions
- Cut off evasive answers ("Thank you — just answer yes or no")
- Use the witness's prior statement contradictions aggressively
- Refer to exhibits and evidence by number
- Never let the witness control the pace

Rules:
1. Canadian criminal evidence rules apply (Criminal Code, Canada Evidence Act)
2. Do not ask compound questions that confuse
3. Tag evasive responses for the scorecard
4. Keep questions under 15 words where possible
5. If the witness is impeached, press the advantage
```

**Step 2: Write examiner module**

Create `backend/llm_agent/examiner.py`:
```python
"""Adversarial Crown prosecutor LLM agent."""

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class ExaminerConfig:
    model: str = "gpt-4"  # or Anthropic / local
    temperature: float = 0.6
    max_tokens: int = 150
    system_prompt_path: str = str(Path(__file__).parent / "prompts" / "examiner_system.txt")

class ExaminerAgent:
    def __init__(self, config: Optional[ExaminerConfig] = None):
        self.config = config or ExaminerConfig()
        self._system_prompt = self._load_prompt()
        self._conversation_history: list[dict] = []

    def _load_prompt(self) -> str:
        with open(self.config.system_prompt_path) as f:
            return f.read()

    def generate_question(self, transcript: str, case_context: dict) -> str:
        """Generate the next cross-examination question based on last witness answer."""
        messages = [
            {"role": "system", "content": self._system_prompt},
            *self._conversation_history[-10:],  # window of last 10 turns
            {"role": "user", "content": f"Witness says: {transcript}\nCase context: {case_context}"}
        ]
        # LLM call goes here — abstracted for now
        # response = openai.chat.completions.create(...)
        question = "I put it to you that you did not see the accused at 8:15 PM."  # placeholder
        self._conversation_history.append({"role": "assistant", "content": question})
        return question

    def log_impeachment(self, transcript: str, prior_statement: str):
        """Record a contradiction for the scorecard."""
        return {
            "type": "impeachment",
            "witness_statement": transcript,
            "prior_statement": prior_statement,
            "timestamp": None,  # set at runtime
        }
```

**Step 3: Boilerplate test**

Create `tests/test_examiner.py`:
```python
import pytest
from backend.llm_agent.examiner import ExaminerAgent, ExaminerConfig

def test_examiner_creates_question():
    agent = ExaminerAgent()
    q = agent.generate_question("I don't recall exactly", {})
    assert isinstance(q, str)
    assert len(q) > 5
```

---

### Task 3.2: Case file ingestion pipeline

**Objective:** Ingest police reports, witness statements, and disclosure documents — extract contradictions and key evidence into structured case context.

**Files:**
- Create: `backend/llm_agent/case_ingestor.py`
- Create: `tests/test_case_ingestor.py`

**Step 1: Write ingestor**

Create `backend/llm_agent/case_ingestor.py`:
```python
"""Ingests criminal case files and extracts structured evidence / contradictions."""

from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class Exhibit:
    id: str
    description: str
    source_file: str

@dataclass
class WitnessStatement:
    witness_id: str
    statement_text: str
    source: str  # e.g., "police statement 2024-03-15", "testimony day 2"

@dataclass
class CaseContext:
    case_id: str
    exhibits: List[Exhibit] = field(default_factory=list)
    witness_statements: List[WitnessStatement] = field(default_factory=list)
    contradictions: List[dict] = field(default_factory=list)

class CaseIngestor:
    def ingest(self, file_paths: List[str]) -> CaseContext:
        """Parse uploaded case files into structured context."""
        context = CaseContext(case_id="temp")
        for path in file_paths:
            text = self._read_file(path)
            extracted = self._extract_statements(text)
            context.witness_statements.extend(extracted)
            exhibits = self._extract_exhibits(text, path)
            context.exhibits.extend(exhibits)
        # Pairwise contradiction scan
        context.contradictions = self._find_contradictions(context.witness_statements)
        return context

    def _read_file(self, path: str) -> str:
        with open(path) as f:
            return f.read()

    def _extract_statements(self, text: str) -> List[WitnessStatement]:
        # MVP: naive extraction — each paragraph is a statement
        lines = [l for l in text.split("\n") if l.strip()]
        return [WitnessStatement(witness_id="unknown", statement_text=l, source="uploaded") for l in lines]

    def _extract_exhibits(self, text: str, source: str) -> List[Exhibit]:
        # MVP: find "Exhibit X:" or "Exhibit X —" patterns
        import re
        exhibits = []
        for match in re.finditer(r"Exhibit\s+(\d+)\s*[:\-–]\s*(.+)", text, re.IGNORECASE):
            exhibits.append(Exhibit(id=match.group(1), description=match.group(2).strip(), source_file=source))
        return exhibits

    def _find_contradictions(self, statements: List[WitnessStatement]) -> List[dict]:
        # MVP: keyword-overlap contradiction flagging
        contradictions = []
        for i, a in enumerate(statements):
            words_a = set(a.statement_text.lower().split())
            for j, b in enumerate(statements):
                if j <= i:
                    continue
                words_b = set(b.statement_text.lower().split())
                if a.witness_id == b.witness_id:
                    # Same witness, check for direct contradictions
                    pass  # LLM-based detection in v2
        return contradictions
```

---

## Phase 4: Post-Examination Pipeline

### Task 4.1: Scorecard engine

**Objective:** After the session ends, generate a structured performance report with impeachment log, contradictions detected, credibility risk rating, and weak-segment links.

**Files:**
- Create: `backend/scorecard/engine.py`
- Create: `tests/test_scorecard.py`

**Step 1: Write scorecard engine**

Create `backend/scorecard/engine.py`:
```python
"""Post-examination scorecard — evaluates witness performance under adversarial questioning."""

from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class ScorecardEntry:
    type: str  # "impeachment", "contradiction", "evidentiary_misstep", "evasive"
    description: str
    severity: str  # "minor", "moderate", "critical"
    timestamp_sec: float
    witness_answer: str
    exhibit_ref: Optional[str] = None
    replay_segment_id: Optional[str] = None

@dataclass
class Scorecard:
    session_id: str
    duration_sec: float
    entries: List[ScorecardEntry] = field(default_factory=list)
    credibility_risk: str = "unknown"  # "low", "moderate", "high"
    weak_segments: List[str] = field(default_factory=list)

    @property
    def impeachment_count(self) -> int:
        return sum(1 for e in self.entries if e.type == "impeachment")

    @property
    def total_contradictions(self) -> int:
        return sum(1 for e in self.entries if e.type == "contradiction")

class ScorecardBuilder:
    def __init__(self, session_id: str):
        self.scorecard = Scorecard(session_id=session_id, duration_sec=0.0)

    def add_entry(self, entry: ScorecardEntry):
        self.scorecard.entries.append(entry)
        self._recalculate_risk()

    def _recalculate_risk(self):
        criticals = sum(1 for e in self.scorecard.entries if e.severity == "critical")
        total = len(self.scorecard.entries)
        if criticals >= 3 or total >= 10:
            self.scorecard.credibility_risk = "high"
        elif criticals >= 1 or total >= 5:
            self.scorecard.credibility_risk = "moderate"
        else:
            self.scorecard.credibility_risk = "low"

    def build(self) -> Scorecard:
        return self.scorecard
```

**Step 2: Write tests**

Create `tests/test_scorecard.py`:
```python
import pytest
from backend.scorecard.engine import ScorecardBuilder, ScorecardEntry

def test_empty_scorecard_is_low_risk():
    builder = ScorecardBuilder("session-1")
    card = builder.build()
    assert card.credibility_risk == "low"
    assert card.impeachment_count == 0

def test_three_criticals_is_high_risk():
    builder = ScorecardBuilder("session-2")
    for i in range(3):
        builder.add_entry(ScorecardEntry(
            type="impeachment", description=f"Critical contradiction {i}",
            severity="critical", timestamp_sec=i * 10.0, witness_answer="I don't recall"
        ))
    assert builder.build().credibility_risk == "high"
```

---

### Task 4.2: Replay segment linker

**Objective:** Tag each audio buffer segment with a timestamp. Scorecard entries reference these segments so the user can instantly replay their weak answers.

**Files:**
- Create: `backend/replay/segment_store.py`
- Create: `tests/test_replay.py`

**Step 1: Write segment store**

Create `backend/replay/segment_store.py`:
```python
"""Stores audio segments tagged by timestamp for targeted replay."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

@dataclass
class AudioSegment:
    segment_id: str
    session_id: str
    start_sec: float
    end_sec: float
    transcript: str
    label: Optional[str] = None  # e.g., "weak_answer", "impeached"

class SegmentStore:
    def __init__(self):
        self._segments: Dict[str, List[AudioSegment]] = {}  # session_id -> segments

    def add_segment(self, segment: AudioSegment):
        self._segments.setdefault(segment.session_id, []).append(segment)

    def get_segments(self, session_id: str, label: Optional[str] = None) -> List[AudioSegment]:
        results = self._segments.get(session_id, [])
        if label:
            results = [s for s in results if s.label == label]
        return sorted(results, key=lambda s: s.start_sec)
```

---

## Phase 5: Integration & Delivery

### Task 5.1: Orchestrator main loop

**Objective:** Wire all modules together into a FastAPI server that manages the full session lifecycle: room creation → VAD + agent loop → scorecard generation → replay delivery.

**Files:**
- Create: `backend/orchestrator/main.py`
- Create: `backend/orchestrator/session_manager.py`

**Step 1: Write session manager**

Create `backend/orchestrator/session_manager.py`:
```python
"""Manages the full cross-examination session lifecycle."""

from dataclasses import dataclass, field
from typing import Optional
from backend.orchestrator.webrtc_gateway import WebRTCGateway, RoomConfig
from backend.llm_agent.examiner import ExaminerAgent, ExaminerConfig
from backend.llm_agent.case_ingestor import CaseContext
from backend.vad_engine.semantic_turn import SemanticTurnDetector
from backend.scorecard.engine import ScorecardBuilder, ScorecardEntry

@dataclass
class Session:
    session_id: str
    room_name: str
    case_context: Optional[CaseContext] = None
    scorecard_builder: Optional[ScorecardBuilder] = None

class SessionManager:
    def __init__(self):
        self._gateway = WebRTCGateway()
        self._examiner = ExaminerAgent()
        self._turn_detector = SemanticTurnDetector()
        self._sessions: dict[str, Session] = {}

    async def create_session(self, session_id: str, case_context: CaseContext) -> Session:
        room_name = await self._gateway.create_room(RoomConfig(name=f"trial-{session_id}"))
        session = Session(
            session_id=session_id,
            room_name=room_name,
            case_context=case_context,
            scorecard_builder=ScorecardBuilder(session_id),
        )
        self._sessions[session_id] = session
        return session

    async def handle_witness_answer(self, session_id: str, transcript: str, pause_ms: float):
        session = self._sessions[session_id]
        if not self._turn_detector.is_turn_complete(transcript, pause_ms):
            return None  # Not done speaking yet
        question = self._examiner.generate_question(transcript, {})
        return question

    def finalize_scorecard(self, session_id: str):
        session = self._sessions[session_id]
        return session.scorecard_builder.build()
```

**Step 2: Write FastAPI entry point**

Create `backend/orchestrator/main.py`:
```python
"""FastAPI entry point — session lifecycle & WebSocket endpoints."""

from fastapi import FastAPI, WebSocket
from contextlib import asynccontextmanager

from backend.orchestrator.session_manager import SessionManager
from backend.llm_agent.case_ingestor import CaseIngestor

manager = SessionManager()
ingestor = CaseIngestor()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: nothing yet
    yield
    # Shutdown: clean up WebRTC gateway
    await manager._gateway.close()

app = FastAPI(title="Witness Prep — Adversarial Cross-Examination", lifespan=lifespan)

@app.post("/session/create")
async def create_session(case_file_paths: list[str]):
    context = ingestor.ingest(case_file_paths)
    session = await manager.create_session(session_id="auto", case_context=context)
    return {"session_id": session.session_id, "room": session.room_name}

@app.websocket("/session/{session_id}/transcript")
async def transcript_stream(websocket: WebSocket, session_id: str):
    await websocket.accept()
    while True:
        data = await websocket.receive_json()
        if data["type"] == "answer":
            question = await manager.handle_witness_answer(
                session_id, data["transcript"], data.get("pause_ms", 0)
            )
            if question:
                await websocket.send_json({"type": "question", "text": question})

@app.get("/session/{session_id}/scorecard")
async def get_scorecard(session_id: str):
    return manager.finalize_scorecard(session_id)
```

---

### Task 5.2: Transcript parallel log (WebSocket)

**Objective:** Background WebSocket log that records every exchange in real-time — usable for post-session review and scorecard evidence.

**Files:**
- Create: `backend/orchestrator/transcript_log.py`

**Step 1: Write transcript logger**

Create `backend/orchestrator/transcript_log.py`:
```python
"""Real-time parallel transcript log — every exchange logged via WebSocket."""

import json
import asyncio
from datetime import datetime
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
            "timestamp": datetime.utcnow().isoformat(),
            "speaker": speaker,
            "text": text,
            "metadata": metadata or {},
        }
        async with self._lock:
            with open(self._log_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
```

---

## Quickstart

```bash
# 1. Start LiveKit
cd ~/Desktop/witness-prep
bash scripts/start_livekit.sh

# 2. Start backend
cd backend
uvicorn orchestrator.main:app --reload --port 8000

# 3. Open frontend
# Serve frontend/src/index.html via any static server
```

---

## Verification Checklist

- [ ] LiveKit container running on 7880-7882
- [ ] WebRTC gateway creates rooms and generates tokens
- [ ] VAD worker detects speech via energy threshold
- [ ] Barge-in interrupt fires over data channel
- [ ] Semantic turn detector correctly classifies complete/incomplete utterances
- [ ] Examiner agent generates adversarial questions
- [ ] Case ingestor extracts statements and exhibits
- [ ] Scorecard builder calculates credibility risk
- [ ] Replay segments are stored and retrievable by session
- [ ] FastAPI server serves all endpoints

---

## Risks & Open Questions

1. **LLM latency** — The 500ms round-trip target assumes a fast inference provider (OpenRouter / Groq / Anthropic). A local model will push this over unless quantized and GPU-accelerated.
2. **Silero WASM size** — ~2MB for the ONNX runtime. Acceptable for MVP but watch first-load time on slow connections.
3. **UDP hole-punching** — SFU behind NAT may need TURN relay. docker-compose exposes port 7882 as TURN TCP; STUN servers are configured.
4. **Audio codec choice** — Opus via WebRTC is the obvious default; confirm LiveKit SFU default matches browser expectations.