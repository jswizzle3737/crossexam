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

from fastapi import FastAPI, HTTPException, Request, UploadFile, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
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

# Serve frontend static assets
app.mount("/static", StaticFiles(directory=str(settings.frontend_dir), html=True), name="frontend")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/")
async def root():
    return FileResponse(settings.frontend_dir / "index.html")


@app.get("/health")
async def health():
    """Liveness check — doesn't require auth."""
    mgr = get_manager()
    try:
        ok = await mgr.gateway.health()
    except Exception:
        ok = False
    return {"status": "ok" if ok else "degraded", "gateway": ok}


@app.post("/case/upload")
async def upload_case(file: UploadFile):
    """Upload a case file (txt, pdf, docx). Saves, ingests, returns case context."""
    import aiofiles
    import os
    upload_dir = settings.data_dir / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    safe_name = file.filename.replace("\\", "_").replace("/", "_")
    save_path = upload_dir / safe_name

    content = await file.read()
    async with aiofiles.open(save_path, "wb") as f:
        await f.write(content)

    # Ingest
    context = ingestor.ingest([str(save_path)])
    return {
        "filename": safe_name,
        "path": str(save_path),
        "case_id": context.case_id,
        "exhibits": [{"id": e.id, "description": e.description} for e in context.exhibits],
        "statements": [{"witness": s.witness_id, "text": s.statement_text[:200]} for s in context.witness_statements],
        "statement_count": len(context.witness_statements),
    }


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
        "case_title": context.case_id,
        "exhibits": [{"id": e.id, "description": e.description} for e in context.exhibits] if context.exhibits else [],
    }


@app.get("/sessions")
async def list_sessions(status: str | None = None):
    """List all sessions, optionally filtered by status."""
    mgr = get_manager()
    from backend.orchestrator.session_manager import SessionStatus
    status_filter = None
    if status:
        try:
            status_filter = SessionStatus(status.upper())
        except ValueError:
            raise HTTPException(400, f"Invalid status: {status}")
    sessions = mgr.list_sessions(status=status_filter)
    return [
        {
            "session_id": s.session_id,
            "status": s.status.name.lower(),
            "turn_number": s.turn_number,
            "case_title": s.case_context.case_id if s.case_context else "",
        }
        for s in sessions
    ]


@app.get("/session/{session_id}")
async def get_session(session_id: str):
    """Get session details without finalizing."""
    mgr = get_manager()
    try:
        session = mgr.get_session(session_id)
    except KeyError:
        raise HTTPException(404, f"Session {session_id} not found")
    return {
        "session_id": session.session_id,
        "status": session.status.name.lower(),
        "turn_number": session.turn_number,
        "case_title": session.case_context.case_id if session.case_context else "",
        "exhibits": [{"id": e.id, "description": e.description} for e in session.case_context.exhibits] if session.case_context and session.case_context.exhibits else [],
    }


@app.post("/session/{session_id}/pause")
async def pause_session(session_id: str):
    """Pause an active session."""
    mgr = get_manager()
    try:
        mgr.pause_session(session_id)
        session = mgr.get_session(session_id)
        return {"session_id": session_id, "status": session.status.name.lower()}
    except KeyError:
        raise HTTPException(404, f"Session {session_id} not found")
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))


@app.post("/session/{session_id}/resume")
async def resume_session(session_id: str):
    """Resume a paused session."""
    mgr = get_manager()
    try:
        mgr.resume_session(session_id)
        session = mgr.get_session(session_id)
        return {"session_id": session_id, "status": session.status.name.lower()}
    except KeyError:
        raise HTTPException(404, f"Session {session_id} not found")
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))


@app.post("/session/{session_id}/destroy")
async def destroy_session(session_id: str):
    """Destroy a session and release its resources."""
    mgr = get_manager()
    try:
        await mgr.destroy_session(session_id)
        return {"session_id": session_id, "status": "destroyed"}
    except KeyError:
        raise HTTPException(404, f"Session {session_id} not found")


@app.get("/session/{session_id}/snapshot")
async def scorecard_snapshot(session_id: str):
    """Get the current scorecard without finalizing the session."""
    mgr = get_manager()
    try:
        scorecard = mgr.scorecard_snapshot(session_id)
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
            }
            for e in scorecard.entries
        ],
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