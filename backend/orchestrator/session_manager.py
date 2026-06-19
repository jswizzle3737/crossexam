"""Manages the full cross-examination session lifecycle.

Design philosophy
-----------------
MAXIMIZE FLEXIBILITY — expose granular control over every phase of a session.
Callers (HTTP handlers in ``main.py``, tests) can:

- Hook into session lifecycle events (created, question, complete)
- Configure per-session examiner strategy and VAD thresholds
- Take mid-session scorecard snapshots without finalizing
- Pause/resume turn detection mid-session
- Manually force a turn boundary, overriding VAD

Owns: WebRTC gateway, examiner agent, VAD turn detection, scorecard, transcript log.

Manages concurrent sessions in an in-memory dict.  Async throughout.
"""

from __future__ import annotations

import asyncio
import logging
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from backend.orchestrator.webrtc_gateway import Room, RoomConfig, WebRTCGateway
from backend.llm_agent.examiner import ExaminerAgent, ExaminerConfig
from backend.llm_agent.case_ingestor import CaseContext
from backend.vad_engine.semantic_turn import SemanticTurnDetector
from backend.scorecard.engine import ScorecardBuilder, Scorecard, ScorecardEntry
from backend.orchestrator.transcript_log import TranscriptLog
from backend.replay.segment_store import SegmentStore, AudioSegment

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------


class SessionStatus(Enum):
    """Lifecycle state of a session."""

    CREATING = auto()
    ACTIVE = auto()
    PAUSED = auto()
    COMPLETED = auto()
    FAILED = auto()


@dataclass
class TurnResult:
    """Result of processing a witness answer turn.

    ``next_question`` is ``None`` when the session is paused, completed, or
    the examiner chooses to stay silent.
    """

    turn_number: int
    next_question: str | None
    is_complete: bool  # True if VAD signalled a full turn
    pause_ms: float
    transcript: str


@dataclass
class TurnOverride:
    """Manual override of the turn-detection boundary.

    Passed to ``force_turn()`` to record a turn boundary irrespective of
    what the VAD engine would say.
    """

    transcript: str
    pause_ms: float = 0.0
    metadata: dict[str, str] | None = None


# ---------------------------------------------------------------------------
# Lifecycle hooks — callers register these for observability / side-effects
# ---------------------------------------------------------------------------


@dataclass
class SessionHooks:
    """Callbacks invoked at key lifecycle points.

    Every callback is ``async`` and receives the owning ``SessionManager``
    as the first argument so it can query other sessions or shared state.
    """

    on_created: Callable[["SessionManager", "Session"], Awaitable[None]] | None = None
    on_question: Callable[["SessionManager", "Session", TurnResult], Awaitable[None]] | None = None
    on_complete: Callable[["SessionManager", "Session", Scorecard], Awaitable[None]] | None = None
    on_pause: Callable[["SessionManager", "Session"], Awaitable[None]] | None = None
    on_resume: Callable[["SessionManager", "Session"], Awaitable[None]] | None = None


# ---------------------------------------------------------------------------
# Per-session configuration
# ---------------------------------------------------------------------------


@dataclass
class SessionConfig:
    """Tune every knob for a single session.

    Most fields have sensible defaults.  Override per-session via the
    ``config`` kwarg on ``create_session()``.
    """

    # Rewrite the default examiner prompt/strategy per session
    examiner_config: ExaminerConfig | None = None

    # VAD tuning — change cadence sensitivity per witness
    vad_pause_threshold_ms: float = 1200.0
    vad_min_words_for_complete: int = 2

    # Logging & replay
    session_dir: Path | None = None
    enable_transcript_log: bool = True
    enable_segment_store: bool = True

    # Room setup
    room_empty_timeout: int = 300

    # Hooks
    hooks: SessionHooks = field(default_factory=SessionHooks)


# ---------------------------------------------------------------------------
# Session — runtime state object
# ---------------------------------------------------------------------------


@dataclass
class Session:
    """Mutable runtime state for one active session."""

    session_id: str
    room_name: str
    room: Room
    config: SessionConfig = field(default_factory=SessionConfig)
    status: SessionStatus = SessionStatus.CREATING
    case_context: Optional[CaseContext] = None
    scorecard_builder: Optional[ScorecardBuilder] = None
    transcript_log: Optional[TranscriptLog] = None
    segment_store: Optional[SegmentStore] = None
    turn_number: int = 0
    examiner_agent: Optional[ExaminerAgent] = None
    turn_detector: Optional[SemanticTurnDetector] = None
    metadata: dict[str, Any] = field(default_factory=dict)  # caller-arbitrary

    # Accumulated transcript buffer for the current partial utterance.
    # Cleared when a turn boundary is detected or forced.
    pending_transcript: str = ""


# ═══════════════════════════════════════════════════════════════════════════
# SessionManager
# ═══════════════════════════════════════════════════════════════════════════


class SessionManager:
    """Owns the full session lifecycle for all active cross-examinations.

    Usage (HTTP handlers in ``main.py``)::

        mgr = SessionManager(gateway_host=..., gateway_port=..., ...)
        await mgr.start()

        session = await mgr.create_session(
            session_id="case-123",
            case_context=context,
            config=SessionConfig(
                hooks=SessionHooks(on_complete=email_notifier),
                examiner_config=ExaminerConfig(model="gpt-4o"),
            ),
        )
        result = await mgr.ingest_witness_answer("I saw him there", pause_ms=300)
        if result.next_question:
            ...

        snapshot = mgr.scorecard_snapshot("case-123")
        mgr.force_turn("case-123", TurnOverride("I mean, uh..."))

        scorecard = await mgr.finalize_scorecard("case-123")
        await mgr.cleanup()
    """

    def __init__(self, **gateway_kwargs: Any) -> None:
        """All keyword arguments forwarded to ``WebRTCGateway.__init__``.

        Legacy prefix: ``gateway_host``, ``gateway_port``, ``gateway_api_key``,
        ``gateway_api_secret`` are automatically mapped to ``host``, ``port``,
        ``api_key``, ``api_secret`` for backward compatibility.

        The gateway is *not* entered here — call ``start()`` before use.
        """
        # Map legacy ``gateway_*`` prefixed kwargs to the names
        # ``WebRTCGateway`` expects (``host``, ``port``, …).
        _PREFIX_MAP: dict[str, str] = {
            "gateway_host": "host",
            "gateway_port": "port",
            "gateway_api_key": "api_key",
            "gateway_api_secret": "api_secret",
        }
        cleaned: dict[str, Any] = {}
        for k, v in gateway_kwargs.items():
            target = _PREFIX_MAP.get(k, k)
            if target in cleaned:
                continue  # explicit kwarg wins over legacy prefix
            cleaned[target] = v

        self._gateway = WebRTCGateway(**cleaned)
        self._sessions: dict[str, Session] = {}

    # ── Lifecycle (called by FastAPI lifespan) ──────────────────────────

    async def start(self) -> None:
        """Open the LiveKit API client (gRPC channel)."""
        await self._gateway.__aenter__()
        logger.info("SessionManager started — gateway connected")

    async def cleanup(self) -> None:
        """Clean up all rooms and close the LiveKit API client.

        Iterates over **every** session (active, paused, completed) and
        removes the remote room.  Best-effort: exceptions are logged but
        not re-raised so all sessions get a chance at cleanup.
        """
        for session_id in list(self._sessions):
            try:
                await self._destroy_session(session_id)
            except Exception:
                logger.exception("Cleanup failed for session %s", session_id)
        self._sessions.clear()
        await self._gateway.__aexit__(None, None, None)
        logger.info("SessionManager cleaned up")

    # ── Session creation / teardown ─────────────────────────────────────

    async def create_session(
        self,
        session_id: str,
        case_context: CaseContext,
        *,
        config: SessionConfig | None = None,
        room_kwargs: dict[str, Any] | None = None,
        examiner: ExaminerAgent | None = None,
        turn_detector: SemanticTurnDetector | None = None,
    ) -> Session:
        """Create a session, create the LiveKit room, return session + token.

        Parameters
        ----------
        session_id:
            Unique identifier.  Overwrites any existing session with the
            same id after cleaning it up.
        case_context:
            Ingested case data (facts, exhibits, prior statements).
        config:
            Per-session configuration (VAD threshold, hooks, strategy …).
            Defaults to ``SessionConfig()``.
        room_kwargs:
            Extra keyword arguments forwarded to ``Room.__init__`` (e.g.
            ``max_participants``, ``empty_timeout``).  Merged *over* the
            values from ``config.room_empty_timeout``.
        examiner:
            Inject a pre-configured ``ExaminerAgent``.  If omitted one is
            created from ``config.examiner_config``.
        turn_detector:
            Inject a pre-configured ``SemanticTurnDetector``.  If omitted
            a default instance is created.

        Returns the ``Session`` object whose ``room`` property can be
        queried for the room name, and whose ``room.generate_token(…)``
        can be called to issue tokens to participants.
        """
        # Tear down any existing session with this id (idempotent)
        if session_id in self._sessions:
            logger.warning("Overwriting existing session %s", session_id)
            await self._destroy_session(session_id)

        config = config or SessionConfig()
        kwargs: dict[str, Any] = {
            "empty_timeout": config.room_empty_timeout,
            **(room_kwargs or {}),
        }

        room = Room(
            gateway=self._gateway,
            config=RoomConfig(name=f"trial-{session_id}"),
            room_name=f"trial-{session_id}",
            **kwargs,
        )
        await room.__aenter__()  # creates room on LiveKit server

        # Build per-session examiner with optional strategy override
        examiner_agent = examiner or ExaminerAgent(
            config=config.examiner_config or ExaminerConfig()
        )

        turn_detector_inst = turn_detector or SemanticTurnDetector()

        scorecard_builder = ScorecardBuilder(session_id)
        transcript_log_inst = (
            TranscriptLog(
                config.session_dir
                or Path.cwd() / "data" / "transcripts" / session_id
            )
            if config.enable_transcript_log
            else None
        )
        segment_store_inst = (
            SegmentStore() if config.enable_segment_store else None
        )

        session = Session(
            session_id=session_id,
            room_name=room.name,
            room=room,
            config=config,
            status=SessionStatus.ACTIVE,
            case_context=case_context,
            scorecard_builder=scorecard_builder,
            transcript_log=transcript_log_inst,
            segment_store=segment_store_inst,
            examiner_agent=examiner_agent,
            turn_detector=turn_detector_inst,
            turn_number=0,
        )
        self._sessions[session_id] = session

        # Invoke lifecycle hook
        hooks = config.hooks
        if hooks.on_created is not None:
            await hooks.on_created(self, session)

        logger.info("Session %s created — room=%s", session_id, room.name)
        return session

    async def destroy_session(self, session_id: str) -> None:
        """Teardown a single session.  Safe to call multiple times."""
        if session_id not in self._sessions:
            return
        await self._destroy_session(session_id)

    async def _destroy_session(self, session_id: str) -> None:
        """Internal — assumes session exists."""
        session = self._sessions.pop(session_id)
        try:
            await session.room.__aexit__(None, None, None)
        except Exception:
            logger.warning("Room cleanup failed for %s", session_id)
        session.status = SessionStatus.COMPLETED

    # ── Ingest witness answer ───────────────────────────────────────────

    async def ingest_witness_answer(
        self,
        session_id: str,
        transcript: str,
        pause_ms: float,
        *,
        auto_log: bool = True,
    ) -> TurnResult:
        """Process a witness utterance.

        Appends ``transcript`` to the session's pending buffer, runs the
        VAD turn detector, and — if a turn boundary is detected —
        generates the next examiner question.

        Parameters
        ----------
        session_id:
            Active session.
        transcript:
            Latest transcript fragment from the witness.
        pause_ms:
            Milliseconds of silence *after* this fragment.
        auto_log:
            If ``True`` (default), the exchange is automatically written to
            the session's ``TranscriptLog``.

        Returns a ``TurnResult`` with the next question (or ``None``) and
        metadata about the turn.

        Raises
        ------
        KeyError
            If ``session_id`` does not exist.
        RuntimeError
            If the session is paused — call ``resume()`` first.
        """
        session = self._sessions[session_id]

        if session.status == SessionStatus.PAUSED:
            raise RuntimeError(
                f"Session {session_id} is paused — call resume() before ingesting"
            )
        if session.status in (SessionStatus.COMPLETED, SessionStatus.FAILED):
            raise RuntimeError(f"Session {session_id} is {session.status.name}")

        session.turn_number += 1
        session.pending_transcript = (session.pending_transcript.strip() + " " + transcript.strip()).strip()

        # Detect turn boundary
        is_complete = session.turn_detector.is_turn_complete(
            session.pending_transcript, pause_ms
        )

        next_question: str | None = None

        if is_complete:
            # Generate next question via examiner agent
            case_dict = (
                session.case_context.to_dict()
                if hasattr(session.case_context, "to_dict")
                else {}
            )
            next_question = await session.examiner_agent.generate_question_async(
                session.pending_transcript, case_dict
            )

            # Log to transcript log
            if auto_log and session.transcript_log is not None:
                await session.transcript_log.log_exchange(
                    turn_number=session.turn_number,
                    speaker="witness",
                    text=session.pending_transcript,
                    metadata={"pause_ms": pause_ms},
                )
                if next_question:
                    await session.transcript_log.log_exchange(
                        turn_number=session.turn_number,
                        speaker="examiner",
                        text=next_question,
                    )

            # Clear pending buffer after a full turn
            session.pending_transcript = ""
        else:
            # Partial utterance — do not clear pending buffer,
            # do not generate a question, but still log the fragment
            if auto_log and session.transcript_log is not None:
                await session.transcript_log.log_exchange(
                    turn_number=session.turn_number,
                    speaker="witness",
                    text=transcript,
                    metadata={"pause_ms": pause_ms, "partial": True},
                )

        result = TurnResult(
            turn_number=session.turn_number,
            next_question=next_question,
            is_complete=is_complete,
            pause_ms=pause_ms,
            transcript=session.pending_transcript if not is_complete else transcript,
        )

        # Invoke lifecycle hook
        hooks = session.config.hooks
        if is_complete and hooks.on_question is not None:
            await hooks.on_question(self, session, result)

        return result

    # ── Manual turn override ────────────────────────────────────────────

    async def force_turn(
        self,
        session_id: str,
        override: TurnOverride,
    ) -> TurnResult:
        """Force a turn boundary **without** VAD.

        This bypasses the ``SemanticTurnDetector`` entirely — the pending
        buffer is treated as a completed turn and the examiner generates a
        question immediately.

        Use cases:
        - The proctor or examiner manually signals "that's the answer".
        - The HTTP caller received an explicit end-of-turn signal outside
          the VAD pipeline.
        - Testing / debug scenarios.
        """
        session = self._sessions[session_id]
        session.turn_number += 1

        # Use whichever transcript is richer
        transcript = override.transcript or session.pending_transcript
        session.pending_transcript = ""

        case_dict = (
            session.case_context.dict_by_alias()
            if hasattr(session.case_context, "dict_by_alias")
            else (
                session.case_context.dict()
                if hasattr(session.case_context, "dict")
                else {}
            )
        )
        next_question = await session.examiner_agent.generate_question_async(
            transcript, case_dict
        )

        return TurnResult(
            turn_number=session.turn_number,
            next_question=next_question,
            is_complete=True,
            pause_ms=override.pause_ms,
            transcript=transcript,
        )

    # ── Pause / Resume ──────────────────────────────────────────────────

    def pause_session(self, session_id: str) -> SessionStatus:
        """Pause turn detection.

        While paused, ``ingest_witness_answer()`` raises
        ``RuntimeError``.  Use ``resume_session()`` to continue.

        Returns the previous status.
        """
        session = self._sessions[session_id]
        prev = session.status
        session.status = SessionStatus.PAUSED
        hooks = session.config.hooks
        if hooks.on_pause is not None:
            asyncio.ensure_future(hooks.on_pause(self, session))
        logger.info("Session %s paused (was %s)", session_id, prev.name)
        return prev

    def resume_session(self, session_id: str) -> SessionStatus:
        """Resume turn detection after a pause.

        Returns the previous status.
        """
        session = self._sessions[session_id]
        prev = session.status
        session.status = SessionStatus.ACTIVE
        hooks = session.config.hooks
        if hooks.on_resume is not None:
            asyncio.ensure_future(hooks.on_resume(self, session))
        logger.info("Session %s resumed (was %s)", session_id, prev.name)
        return prev

    # ── Scorecard operations ────────────────────────────────────────────

    def scorecard_snapshot(self, session_id: str) -> Scorecard:
        """Return a **copy** of the current scorecard without finalising.

        Unlike ``finalize_scorecard()`` this does *not* mark the session
        as complete.  Callers can use it to render in-progress UI or
        stream partial results.
        """
        session = self._sessions[session_id]
        return deepcopy(session.scorecard_builder.build())

    def add_scorecard_entry(self, session_id: str, entry: ScorecardEntry) -> None:
        """Add a scorecard entry mid-session (e.g. from an examiner)."""
        session = self._sessions[session_id]
        session.scorecard_builder.add_entry(entry)

    async def finalize_scorecard(self, session_id: str) -> Scorecard:
        """Finalise the scorecard and mark the session as completed.

        Returns the built ``Scorecard``.  After calling this, the session
        is in the ``COMPLETED`` state and can no longer ingest answers.

        To keep the session active for more turns, use
        ``scorecard_snapshot()`` instead.
        """
        session = self._sessions[session_id]
        session.status = SessionStatus.COMPLETED
        scorecard = session.scorecard_builder.build()

        hooks = session.config.hooks
        if hooks.on_complete is not None:
            await hooks.on_complete(self, session, scorecard)

        logger.info(
            "Session %s scorecard finalised — %d entries, risk=%s",
            session_id,
            len(scorecard.entries),
            scorecard.credibility_risk,
        )
        return scorecard

    # ── Ingest convenience ──────────────────────────────────────────────

    async def ingest_and_auto_finalize(
        self,
        session_id: str,
        transcript: str,
        pause_ms: float,
    ) -> dict[str, Any]:
        """Convenience: ingest, auto-finalise if complete, return full state.

        Returns a dict with keys ``turn_result``, ``scorecard`` (or None),
        and ``session_status``.  Designed for simple callers that want a
        single call instead of two.
        """
        result = await self.ingest_witness_answer(session_id, transcript, pause_ms)
        resp: dict[str, Any] = {
            "turn_result": result,
            "scorecard": None,
            "session_status": self._sessions[session_id].status.name,
        }
        if result.is_complete and self._sessions[session_id].status != SessionStatus.COMPLETED:
            resp["scorecard"] = await self.finalize_scorecard(session_id)
        return resp

    # ── Query / introspection ───────────────────────────────────────────

    def get_session(self, session_id: str) -> Session:
        """Get a session by id.  Raises ``KeyError`` if missing."""
        return self._sessions[session_id]

    def list_sessions(
        self,
        *,
        status: SessionStatus | None = None,
    ) -> list[Session]:
        """List active sessions, optionally filtered by status."""
        sessions = list(self._sessions.values())
        if status is not None:
            sessions = [s for s in sessions if s.status == status]
        return sessions

    @property
    def active_session_count(self) -> int:
        """Number of sessions that are not completed/failed."""
        return sum(
            1
            for s in self._sessions.values()
            if s.status not in (SessionStatus.COMPLETED, SessionStatus.FAILED)
        )

    @property
    def gateway(self) -> WebRTCGateway:
        """Expose the underlying gateway for advanced callers (e.g. admin scripts)."""
        return self._gateway
