"""FastAPI entry point — session lifecycle & WebSocket endpoints.

Credentials for the LiveKit gateway are read from ``backend.config.settings`` (``.env``).

Middleware stack (applied top-to-bottom):
1. CORS — permissive in dev, locked in prod (via ``CORS_ORIGINS`` env)
2. Auth — Bearer token validated on every request except public paths
3. Rate limiting — token-bucket per API key
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from time import monotonic

from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

from backend.config import settings
from backend.llm_agent.case_ingestor import CaseIngestor
from backend.orchestrator.session_manager import SessionManager

_manager: SessionManager | None = None
ingestor = CaseIngestor()


def get_manager() -> SessionManager:
    global _manager
    if _manager is None:
        _manager = SessionManager(
            gateway_host=settings.livekit_host,
            gateway_port=settings.livekit_port,
            gateway_api_key=settings.livekit_api_key,
            gateway_api_secret=settings.livekit_api_secret,
        )
    return _manager


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

PUBLIC_PATHS = frozenset({"/docs", "/openapi.json", "/redoc", "/health", "/"})


class AuthMiddleware(BaseHTTPMiddleware):
    """Validates Bearer token or ``?token=`` query param against configured API keys.

    Skips public paths and allows WebSocket handshake via query-param token.
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in PUBLIC_PATHS:
            return await call_next(request)

        token = request.query_params.get("token")
        if not token:
            auth_header = request.headers.get("authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]

        if not token or token not in settings.api_keys:
            return JSONResponse(status_code=401, content={"detail": "Invalid or missing API key"})

        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """In-memory token-bucket rate limiter per API key / IP."""

    def __init__(self, app, max_requests: int = 120, window_seconds: int = 60):
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._buckets: dict[str, list[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in PUBLIC_PATHS:
            return await call_next(request)

        # Use client IP or API key as identity
        token = request.query_params.get("token") or request.headers.get("authorization", "")
        identity = token or request.client.host if request.client else "unknown"

        now = monotonic()
        bucket = self._buckets[identity]
        bucket[:] = [t for t in bucket if now - t < self.window_seconds]

        if len(bucket) >= self.max_requests:
            return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded. Try again later."})

        bucket.append(now)
        return await call_next(request)


# ---------------------------------------------------------------------------
# App assembly
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    mgr = get_manager()
    await mgr.start()
    yield
    await mgr.cleanup()


app = FastAPI(title="Witness Prep — Adversarial Cross-Examination", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AuthMiddleware)
app.add_middleware(RateLimitMiddleware)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/")
async def root():
    return RedirectResponse(url="/docs")


@app.get("/health")
async def health():
    """Liveness check — doesn't require auth."""
    mgr = get_manager()
    try:
        ok = await mgr.gateway.health()
    except Exception:
        ok = False
    return {"status": "ok" if ok else "degraded", "gateway": ok}


@app.post("/session/create")
async def create_session(case_file_paths: list[str]):
    """Create a new cross-examination session.

    Accepts case file paths, ingests them, provisions a LiveKit room, and
    returns the session ID, room name, and JWT token.
    """
    context = ingestor.ingest(case_file_paths)
    session_id = f"ses_{uuid.uuid4().hex[:8]}"
    session = await get_manager().create_session(
        session_id=session_id,
        case_context=context,
    )
    token = await session.room.generate_token(
        identity="witness",
        ttl_seconds=3600,
    )
    return {
        "session_id": session.session_id,
        "room": session.room_name,
        "token": token,
    }


@app.websocket("/session/{session_id}/transcript")
async def transcript_stream(websocket: WebSocket, session_id: str):
    """WebSocket for real-time transcript streaming.

    Auth: pass ``?token=<api_key>`` in the WebSocket URL (browser EventSource /
    native WebSocket can't set custom headers).

    Protocol (JSON messages):
      C->S  {"type": "answer", "transcript": "...", "pause_ms": N}
      S->C  {"type": "question", "text": "...", "strategy": "..."}
      S->C  {"type": "error", "code": "SESSION_NOT_FOUND"}
    """
    # Auth check on handshake (before accept)
    ws_token = websocket.query_params.get("token", "")
    if ws_token not in settings.api_keys:
        await websocket.close(code=4001)
        return

    await websocket.accept()
    while True:
        try:
            data = await websocket.receive_json()
        except Exception:
            break  # Client disconnected

        if data.get("type") != "answer":
            await websocket.send_json({"type": "error", "code": "INVALID_TYPE"})
            continue

        try:
            result = await get_manager().ingest_witness_answer(
                session_id=session_id,
                transcript=data["transcript"],
                pause_ms=data.get("pause_ms", 0),
            )
        except KeyError:
            await websocket.send_json({"type": "error", "code": "SESSION_NOT_FOUND"})
            continue
        except RuntimeError as exc:
            await websocket.send_json({"type": "error", "code": "SESSION_STATE", "message": str(exc)})
            continue

        if result.next_question:
            await websocket.send_json({"type": "question", "text": result.next_question})


@app.get("/session/{session_id}/scorecard")
async def get_scorecard(session_id: str):
    """Finalize the session and return the completed scorecard.

    This also tears down the LiveKit room and releases session resources.
    """
    try:
        scorecard = await get_manager().finalize_scorecard(session_id)
    except KeyError:
        raise HTTPException(404, f"Session {session_id} not found")

    return {
        "session_id": scorecard.session_id,
        "duration_sec": scorecard.duration_sec,
        "credibility_risk": scorecard.credibility_risk,
        "entries": [
            {
                "type": e.type,
                "description": e.description,
                "severity": e.severity,
                "timestamp_sec": e.timestamp_sec,
                "witness_answer": e.witness_answer,
                "exhibit_ref": e.exhibit_ref,
                "replay_segment_id": e.replay_segment_id,
            }
            for e in scorecard.entries
        ],
    }