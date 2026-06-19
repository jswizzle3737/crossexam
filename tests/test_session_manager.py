"""Comprehensive SessionManager tests — covers all state-machine transitions."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.orchestrator.session_manager import (
    SessionManager,
    SessionConfig,
    SessionHooks,
    SessionStatus,
    TurnOverride,
)
from backend.llm_agent.case_ingestor import CaseContext, Exhibit, WitnessStatement


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_gateway():
    with patch("backend.orchestrator.session_manager.WebRTCGateway") as cls:
        instance = MagicMock()
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=None)
        instance.health = AsyncMock(return_value=True)
        cls.return_value = instance
        yield cls


@pytest.fixture
def case_context():
    return CaseContext(
        case_id="case-1",
        exhibits=[Exhibit(id="1", description="Photo of scene", source_file="photo.jpg")],
        witness_statements=[
            WitnessStatement(witness_id="w1", statement_text="I saw him at 8pm", source="dep.txt")
        ],
        contradictions=[{"witness": "w1", "claim": "time"}],
    )


@pytest.fixture
def mock_room():
    room = MagicMock()
    room.name = "trial-ses_abc123"
    room.__aenter__ = AsyncMock(return_value=room)
    room.__aexit__ = AsyncMock(return_value=None)
    room.generate_token = AsyncMock(return_value="fake-jwt-token")
    return room


@pytest.fixture
def mock_turn_detector():
    det = MagicMock()
    det.is_turn_complete = MagicMock(return_value=False)
    return det


@pytest.fixture
def mock_examiner():
    exam = MagicMock()
    exam.generate_question = MagicMock(return_value="Next question?")
    exam.generate_question_async = AsyncMock(return_value="Next question?")
    return exam


@pytest.fixture
def mock_transcript_log():
    log = MagicMock()
    log.log_exchange = AsyncMock()
    return log


# ---------------------------------------------------------------------------
# create_session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_session_initializes_all_components(
    mock_gateway, case_context, mock_room, mock_turn_detector, mock_examiner, mock_transcript_log
):
    """create_session builds a Session with all sub-systems wired up."""
    with (
        patch("backend.orchestrator.session_manager.Room", return_value=mock_room),
        patch("backend.orchestrator.session_manager.SemanticTurnDetector", return_value=mock_turn_detector),
        patch("backend.orchestrator.session_manager.ExaminerAgent", return_value=mock_examiner),
        patch("backend.orchestrator.session_manager.TranscriptLog", return_value=mock_transcript_log),
    ):
        mgr = SessionManager(gateway_api_key="k", gateway_api_secret="s")
        await mgr.start()
        session = await mgr.create_session(session_id="ses_abc123", case_context=case_context)
        assert session.session_id == "ses_abc123"
        assert session.status == SessionStatus.ACTIVE
        assert session.examiner_agent is mock_examiner
        assert session.turn_detector is mock_turn_detector
        assert session.transcript_log is mock_transcript_log
        assert session.turn_number == 0
        await mgr.cleanup()


@pytest.mark.asyncio
async def test_create_session_calls_room_enter(mock_gateway, case_context, mock_room):
    """The LiveKit room is entered (created on server) during create_session."""
    with (
        patch("backend.orchestrator.session_manager.Room", return_value=mock_room),
        patch("backend.orchestrator.session_manager.SemanticTurnDetector"),
        patch("backend.orchestrator.session_manager.ExaminerAgent"),
    ):
        mgr = SessionManager(gateway_api_key="k", gateway_api_secret="s")
        await mgr.start()
        await mgr.create_session(session_id="ses_test", case_context=case_context)
        mock_room.__aenter__.assert_awaited_once()
        await mgr.cleanup()


@pytest.mark.asyncio
async def test_create_session_fires_on_created_hook(mock_gateway, case_context, mock_room):
    """The on_created hook is called after session construction."""
    hook_session = None

    async def on_created(mgr, session):
        nonlocal hook_session
        hook_session = session

    config = SessionConfig(hooks=SessionHooks(on_created=on_created))
    with (
        patch("backend.orchestrator.session_manager.Room", return_value=mock_room),
        patch("backend.orchestrator.session_manager.SemanticTurnDetector"),
        patch("backend.orchestrator.session_manager.ExaminerAgent"),
    ):
        mgr = SessionManager(gateway_api_key="k", gateway_api_secret="s")
        await mgr.start()
        session = await mgr.create_session(session_id="ses_hook", case_context=case_context, config=config)
        assert hook_session is session
        await mgr.cleanup()


@pytest.mark.asyncio
async def test_create_session_idempotent_overwrite(mock_gateway, case_context):
    """Creating a session with an existing id cleans up the old one first."""
    old_room = MagicMock()
    old_room.name = "trial-old"
    old_room.__aexit__ = AsyncMock()

    new_room = MagicMock()
    new_room.name = "trial-new"
    new_room.__aenter__ = AsyncMock(return_value=new_room)
    new_room.__aexit__ = AsyncMock()

    with (
        patch("backend.orchestrator.session_manager.Room", side_effect=[old_room, new_room]),
        patch("backend.orchestrator.session_manager.SemanticTurnDetector"),
        patch("backend.orchestrator.session_manager.ExaminerAgent"),
    ):
        mgr = SessionManager(gateway_api_key="k", gateway_api_secret="s")
        await mgr.start()
        s1 = await mgr.create_session(session_id="dup", case_context=case_context)
        assert s1.room.name == "trial-old"
        s2 = await mgr.create_session(session_id="dup", case_context=case_context)
        assert s2.room.name == "trial-new"
        old_room.__aexit__.assert_awaited_once()
        await mgr.cleanup()


# ---------------------------------------------------------------------------
# ingest_witness_answer — partial turn (VAD incomplete)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_partial_turn_no_question(mock_gateway, case_context, mock_room, mock_examiner):
    """A partial utterance (VAD incomplete) does not generate a question."""
    mock_detector = MagicMock()
    mock_detector.is_turn_complete = MagicMock(return_value=False)

    with (
        patch("backend.orchestrator.session_manager.Room", return_value=mock_room),
        patch("backend.orchestrator.session_manager.SemanticTurnDetector", return_value=mock_detector),
        patch("backend.orchestrator.session_manager.ExaminerAgent", return_value=mock_examiner),
    ):
        mgr = SessionManager(gateway_api_key="k", gateway_api_secret="s")
        await mgr.start()
        await mgr.create_session(session_id="ses_partial", case_context=case_context)
        result = await mgr.ingest_witness_answer(session_id="ses_partial", transcript="I saw him", pause_ms=300)
        assert result.is_complete is False
        assert result.next_question is None
        assert result.transcript == "I saw him"
        mock_examiner.generate_question_async.assert_not_called()
        await mgr.cleanup()


@pytest.mark.asyncio
async def test_ingest_partial_turn_accumulates_buffer(mock_gateway, case_context, mock_room):
    """Partial utterances are accumulated in pending_transcript."""
    mock_detector = MagicMock()
    mock_detector.is_turn_complete = MagicMock(return_value=False)

    with (
        patch("backend.orchestrator.session_manager.Room", return_value=mock_room),
        patch("backend.orchestrator.session_manager.SemanticTurnDetector", return_value=mock_detector),
        patch("backend.orchestrator.session_manager.ExaminerAgent"),
    ):
        mgr = SessionManager(gateway_api_key="k", gateway_api_secret="s")
        await mgr.start()
        await mgr.create_session(session_id="ses_buf", case_context=case_context)
        await mgr.ingest_witness_answer(session_id="ses_buf", transcript="I saw him", pause_ms=100)
        await mgr.ingest_witness_answer(session_id="ses_buf", transcript=" at the scene", pause_ms=100)
        await mgr.ingest_witness_answer(session_id="ses_buf", transcript=" that night", pause_ms=100)
        assert mgr.get_session("ses_buf").pending_transcript == "I saw him at the scene that night"
        await mgr.cleanup()


# ---------------------------------------------------------------------------
# ingest_witness_answer — complete turn (VAD complete)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_complete_turn_generates_question(
    mock_gateway, case_context, mock_room, mock_examiner
):
    """A complete utterance triggers examiner question + transcript log."""
    mock_log = MagicMock()
    mock_log.log_exchange = AsyncMock()
    mock_detector = MagicMock()
    mock_detector.is_turn_complete = MagicMock(return_value=True)

    with (
        patch("backend.orchestrator.session_manager.Room", return_value=mock_room),
        patch("backend.orchestrator.session_manager.SemanticTurnDetector", return_value=mock_detector),
        patch("backend.orchestrator.session_manager.ExaminerAgent", return_value=mock_examiner),
        patch("backend.orchestrator.session_manager.TranscriptLog", return_value=mock_log),
    ):
        mgr = SessionManager(gateway_api_key="k", gateway_api_secret="s")
        await mgr.start()
        await mgr.create_session(session_id="ses_full", case_context=case_context)
        result = await mgr.ingest_witness_answer(
            session_id="ses_full", transcript="I saw him at 8pm", pause_ms=1500
        )
        assert result.is_complete is True
        assert result.next_question == "Next question?"
        mock_examiner.generate_question_async.assert_called_once()
        assert mgr.get_session("ses_full").pending_transcript == ""
        await mgr.cleanup()


@pytest.mark.asyncio
async def test_ingest_complete_turn_logs_both_speaker_lines(
    mock_gateway, case_context, mock_room, mock_examiner
):
    """A complete turn logs witness answer + examiner question."""
    mock_log = MagicMock()
    mock_log.log_exchange = AsyncMock()
    mock_detector = MagicMock()
    mock_detector.is_turn_complete = MagicMock(return_value=True)

    with (
        patch("backend.orchestrator.session_manager.Room", return_value=mock_room),
        patch("backend.orchestrator.session_manager.SemanticTurnDetector", return_value=mock_detector),
        patch("backend.orchestrator.session_manager.ExaminerAgent", return_value=mock_examiner),
        patch("backend.orchestrator.session_manager.TranscriptLog", return_value=mock_log),
    ):
        mgr = SessionManager(gateway_api_key="k", gateway_api_secret="s")
        await mgr.start()
        await mgr.create_session(session_id="ses_log", case_context=case_context)
        await mgr.ingest_witness_answer(session_id="ses_log", transcript="The light was green", pause_ms=2000)
        assert mock_log.log_exchange.call_count == 2
        witness_call = mock_log.log_exchange.call_args_list[0]
        examiner_call = mock_log.log_exchange.call_args_list[1]
        assert witness_call.kwargs["speaker"] == "witness"
        assert examiner_call.kwargs["speaker"] == "examiner"
        await mgr.cleanup()


@pytest.mark.asyncio
async def test_ingest_complete_turn_fires_on_question_hook(
    mock_gateway, case_context, mock_room, mock_examiner
):
    """on_question hook fires after a complete turn."""
    hook_calls = []

    async def on_question(mgr, session, result):
        hook_calls.append(result)

    config = SessionConfig(hooks=SessionHooks(on_question=on_question))
    mock_log = MagicMock()
    mock_log.log_exchange = AsyncMock()
    mock_detector = MagicMock()
    mock_detector.is_turn_complete = MagicMock(return_value=True)

    with (
        patch("backend.orchestrator.session_manager.Room", return_value=mock_room),
        patch("backend.orchestrator.session_manager.SemanticTurnDetector", return_value=mock_detector),
        patch("backend.orchestrator.session_manager.ExaminerAgent", return_value=mock_examiner),
        patch("backend.orchestrator.session_manager.TranscriptLog", return_value=mock_log),
    ):
        mgr = SessionManager(gateway_api_key="k", gateway_api_secret="s")
        await mgr.start()
        await mgr.create_session(session_id="ses_hookq", case_context=case_context, config=config)
        await mgr.ingest_witness_answer(session_id="ses_hookq", transcript="Yes I was there", pause_ms=2000)
        assert len(hook_calls) == 1
        assert hook_calls[0].is_complete is True
        await mgr.cleanup()


# ---------------------------------------------------------------------------
# ingest_witness_answer — case context
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_passes_case_context_to_examiner(mock_gateway, case_context, mock_room):
    """CaseContext.to_dict() is called and passed to the examiner."""
    mock_examiner = MagicMock()
    mock_examiner.generate_question_async = AsyncMock(return_value="?")
    mock_detector = MagicMock()
    mock_detector.is_turn_complete = MagicMock(return_value=True)
    mock_log = MagicMock()
    mock_log.log_exchange = AsyncMock()

    with (
        patch("backend.orchestrator.session_manager.Room", return_value=mock_room),
        patch("backend.orchestrator.session_manager.SemanticTurnDetector", return_value=mock_detector),
        patch("backend.orchestrator.session_manager.ExaminerAgent", return_value=mock_examiner),
        patch("backend.orchestrator.session_manager.TranscriptLog", return_value=mock_log),
    ):
        mgr = SessionManager(gateway_api_key="k", gateway_api_secret="s")
        await mgr.start()
        await mgr.create_session(session_id="ses_ctx", case_context=case_context)
        await mgr.ingest_witness_answer(session_id="ses_ctx", transcript="Answer text", pause_ms=2000)
        call_args = mock_examiner.generate_question_async.call_args
        case_dict = call_args[0][1]
        assert case_dict["case_id"] == "case-1"
        assert len(case_dict["exhibits"]) == 1
        assert case_dict["exhibits"][0]["id"] == "1"
        assert len(case_dict["witness_statements"]) == 1
        await mgr.cleanup()


# ---------------------------------------------------------------------------
# ingest_witness_answer — state guards
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_raises_on_paused_session(mock_gateway, case_context, mock_room):
    """ingest_witness_answer raises RuntimeError when session is PAUSED."""
    with (
        patch("backend.orchestrator.session_manager.Room", return_value=mock_room),
        patch("backend.orchestrator.session_manager.SemanticTurnDetector"),
        patch("backend.orchestrator.session_manager.ExaminerAgent"),
    ):
        mgr = SessionManager(gateway_api_key="k", gateway_api_secret="s")
        await mgr.start()
        await mgr.create_session(session_id="ses_pause", case_context=case_context)
        mgr.pause_session("ses_pause")
        with pytest.raises(RuntimeError, match="paused"):
            await mgr.ingest_witness_answer(session_id="ses_pause", transcript="late answer", pause_ms=100)
        await mgr.cleanup()


@pytest.mark.asyncio
async def test_ingest_raises_on_completed_session(mock_gateway, case_context, mock_room):
    """ingest_witness_answer raises RuntimeError when session is COMPLETED."""
    with (
        patch("backend.orchestrator.session_manager.Room", return_value=mock_room),
        patch("backend.orchestrator.session_manager.SemanticTurnDetector"),
        patch("backend.orchestrator.session_manager.ExaminerAgent"),
    ):
        mgr = SessionManager(gateway_api_key="k", gateway_api_secret="s")
        await mgr.start()
        await mgr.create_session(session_id="ses_done", case_context=case_context)
        mgr._sessions["ses_done"].status = SessionStatus.COMPLETED
        with pytest.raises(RuntimeError, match="COMPLETED"):
            await mgr.ingest_witness_answer(session_id="ses_done", transcript="too late", pause_ms=100)
        await mgr.cleanup()


@pytest.mark.asyncio
async def test_ingest_raises_on_unknown_session(mock_gateway, case_context, mock_room):
    """ingest_witness_answer raises KeyError for unknown session id."""
    with (
        patch("backend.orchestrator.session_manager.Room", return_value=mock_room),
        patch("backend.orchestrator.session_manager.SemanticTurnDetector"),
        patch("backend.orchestrator.session_manager.ExaminerAgent"),
    ):
        mgr = SessionManager(gateway_api_key="k", gateway_api_secret="s")
        await mgr.start()
        await mgr.create_session(session_id="ses_known", case_context=case_context)
        with pytest.raises(KeyError):
            await mgr.ingest_witness_answer(session_id="ses_unknown", transcript="bad session", pause_ms=100)
        await mgr.cleanup()


# ---------------------------------------------------------------------------
# force_turn
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_force_turn_bypasses_vad(mock_gateway, case_context, mock_room, mock_examiner):
    """force_turn generates a question even when VAD would not fire."""
    mock_detector = MagicMock()
    mock_detector.is_turn_complete = MagicMock(return_value=False)
    mock_log = MagicMock()
    mock_log.log_exchange = AsyncMock()

    with (
        patch("backend.orchestrator.session_manager.Room", return_value=mock_room),
        patch("backend.orchestrator.session_manager.SemanticTurnDetector", return_value=mock_detector),
        patch("backend.orchestrator.session_manager.ExaminerAgent", return_value=mock_examiner),
        patch("backend.orchestrator.session_manager.TranscriptLog", return_value=mock_log),
    ):
        mgr = SessionManager(gateway_api_key="k", gateway_api_secret="s")
        await mgr.start()
        await mgr.create_session(session_id="ses_force", case_context=case_context)
        result = await mgr.force_turn("ses_force", TurnOverride(transcript="Manual override text"))
        assert result.is_complete is True
        assert result.transcript == "Manual override text"
        mock_detector.is_turn_complete.assert_not_called()
        await mgr.cleanup()


@pytest.mark.asyncio
async def test_force_turn_increments_turn_number(mock_gateway, case_context, mock_room):
    """force_turn advances the turn counter."""
    mock_detector = MagicMock()
    mock_detector.is_turn_complete = MagicMock(return_value=False)
    mock_examiner = MagicMock()
    mock_examiner.generate_question_async = AsyncMock(return_value="?")
    with (
        patch("backend.orchestrator.session_manager.Room", return_value=mock_room),
        patch("backend.orchestrator.session_manager.SemanticTurnDetector", return_value=mock_detector),
        patch("backend.orchestrator.session_manager.ExaminerAgent", return_value=mock_examiner),
    ):
        mgr = SessionManager(gateway_api_key="k", gateway_api_secret="s")
        await mgr.start()
        await mgr.create_session(session_id="ses_tn", case_context=case_context)
        assert mgr.get_session("ses_tn").turn_number == 0
        await mgr.force_turn("ses_tn", TurnOverride(transcript="First"))
        assert mgr.get_session("ses_tn").turn_number == 1
        await mgr.force_turn("ses_tn", TurnOverride(transcript="Second"))
        assert mgr.get_session("ses_tn").turn_number == 2
        await mgr.cleanup()


# ---------------------------------------------------------------------------
# pause / resume
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pause_session_sets_status(mock_gateway, case_context, mock_room):
    """pause_session transitions ACTIVE → PAUSED."""
    with (
        patch("backend.orchestrator.session_manager.Room", return_value=mock_room),
        patch("backend.orchestrator.session_manager.SemanticTurnDetector"),
        patch("backend.orchestrator.session_manager.ExaminerAgent"),
    ):
        mgr = SessionManager(gateway_api_key="k", gateway_api_secret="s")
        await mgr.start()
        await mgr.create_session(session_id="ses_ps", case_context=case_context)
        assert mgr.get_session("ses_ps").status == SessionStatus.ACTIVE
        prev = mgr.pause_session("ses_ps")
        assert prev == SessionStatus.ACTIVE
        assert mgr.get_session("ses_ps").status == SessionStatus.PAUSED
        await mgr.cleanup()


@pytest.mark.asyncio
async def test_resume_session_restores_active(mock_gateway, case_context, mock_room):
    """resume_session transitions PAUSED → ACTIVE."""
    with (
        patch("backend.orchestrator.session_manager.Room", return_value=mock_room),
        patch("backend.orchestrator.session_manager.SemanticTurnDetector"),
        patch("backend.orchestrator.session_manager.ExaminerAgent"),
    ):
        mgr = SessionManager(gateway_api_key="k", gateway_api_secret="s")
        await mgr.start()
        await mgr.create_session(session_id="ses_rs", case_context=case_context)
        mgr.pause_session("ses_rs")
        prev = mgr.resume_session("ses_rs")
        assert prev == SessionStatus.PAUSED
        assert mgr.get_session("ses_rs").status == SessionStatus.ACTIVE
        await mgr.cleanup()


# ---------------------------------------------------------------------------
# scorecard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scorecard_snapshot_returns_independent_copy(mock_gateway, case_context, mock_room):
    """scorecard_snapshot returns a deepcopy — mutations don't affect session state."""
    with (
        patch("backend.orchestrator.session_manager.Room", return_value=mock_room),
        patch("backend.orchestrator.session_manager.SemanticTurnDetector"),
        patch("backend.orchestrator.session_manager.ExaminerAgent"),
    ):
        mgr = SessionManager(gateway_api_key="k", gateway_api_secret="s")
        await mgr.start()
        await mgr.create_session(session_id="ses_sc", case_context=case_context)
        snap1 = mgr.scorecard_snapshot("ses_sc")
        snap1.entries.append("mutated")
        snap2 = mgr.scorecard_snapshot("ses_sc")
        assert snap2.entries == []
        await mgr.cleanup()


@pytest.mark.asyncio
async def test_add_scorecard_entry(mock_gateway, case_context, mock_room):
    """add_scorecard_entry adds an entry to the session's scorecard."""
    from backend.scorecard.engine import ScorecardEntry

    with (
        patch("backend.orchestrator.session_manager.Room", return_value=mock_room),
        patch("backend.orchestrator.session_manager.SemanticTurnDetector"),
        patch("backend.orchestrator.session_manager.ExaminerAgent"),
    ):
        mgr = SessionManager(gateway_api_key="k", gateway_api_secret="s")
        await mgr.start()
        await mgr.create_session(session_id="ses_se", case_context=case_context)
        entry = ScorecardEntry(
            type="impeachment",
            description="Witness changed story",
            severity="critical",
            timestamp_sec=10.0,
            witness_answer="I was there",
        )
        mgr.add_scorecard_entry("ses_se", entry)
        snap = mgr.scorecard_snapshot("ses_se")
        assert len(snap.entries) == 1
        assert snap.entries[0].type == "impeachment"
        await mgr.cleanup()


@pytest.mark.asyncio
async def test_finalize_scorecard_transitions_to_completed(mock_gateway, case_context, mock_room):
    """finalize_scorecard sets session status to COMPLETED."""
    with (
        patch("backend.orchestrator.session_manager.Room", return_value=mock_room),
        patch("backend.orchestrator.session_manager.SemanticTurnDetector"),
        patch("backend.orchestrator.session_manager.ExaminerAgent"),
    ):
        mgr = SessionManager(gateway_api_key="k", gateway_api_secret="s")
        await mgr.start()
        await mgr.create_session(session_id="ses_fs", case_context=case_context)
        assert mgr.get_session("ses_fs").status == SessionStatus.ACTIVE
        await mgr.finalize_scorecard("ses_fs")
        assert mgr.get_session("ses_fs").status == SessionStatus.COMPLETED
        await mgr.cleanup()


@pytest.mark.asyncio
async def test_finalize_scorecard_fires_on_complete_hook(mock_gateway, case_context, mock_room):
    """finalize_scorecard invokes on_complete with the scorecard."""
    hook_calls = []

    async def on_complete(mgr, session, scorecard):
        hook_calls.append(scorecard)

    config = SessionConfig(hooks=SessionHooks(on_complete=on_complete))
    with (
        patch("backend.orchestrator.session_manager.Room", return_value=mock_room),
        patch("backend.orchestrator.session_manager.SemanticTurnDetector"),
        patch("backend.orchestrator.session_manager.ExaminerAgent"),
    ):
        mgr = SessionManager(gateway_api_key="k", gateway_api_secret="s")
        await mgr.start()
        await mgr.create_session(session_id="ses_oc", case_context=case_context, config=config)
        scorecard = await mgr.finalize_scorecard("ses_oc")
        assert len(hook_calls) == 1
        assert hook_calls[0] is scorecard
        await mgr.cleanup()


# ---------------------------------------------------------------------------
# ingest_and_auto_finalize
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_and_auto_finalize_closes_on_complete_turn(mock_gateway, case_context, mock_room, mock_examiner):
    """ingest_and_auto_finalize auto-closes the session after a complete turn."""
    mock_log = MagicMock()
    mock_log.log_exchange = AsyncMock()
    mock_detector = MagicMock()
    mock_detector.is_turn_complete = MagicMock(return_value=True)

    with (
        patch("backend.orchestrator.session_manager.Room", return_value=mock_room),
        patch("backend.orchestrator.session_manager.SemanticTurnDetector", return_value=mock_detector),
        patch("backend.orchestrator.session_manager.ExaminerAgent", return_value=mock_examiner),
        patch("backend.orchestrator.session_manager.TranscriptLog", return_value=mock_log),
    ):
        mgr = SessionManager(gateway_api_key="k", gateway_api_secret="s")
        await mgr.start()
        await mgr.create_session(session_id="ses_af", case_context=case_context)
        resp = await mgr.ingest_and_auto_finalize(session_id="ses_af", transcript="I was there", pause_ms=2000)
        assert resp["scorecard"] is not None
        assert mgr.get_session("ses_af").status == SessionStatus.COMPLETED
        await mgr.cleanup()


@pytest.mark.asyncio
async def test_ingest_and_auto_finalize_stays_open_on_partial_turn(mock_gateway, case_context, mock_room):
    """ingest_and_auto_finalize does not close on partial turn."""
    mock_detector = MagicMock()
    mock_detector.is_turn_complete = MagicMock(return_value=False)

    with (
        patch("backend.orchestrator.session_manager.Room", return_value=mock_room),
        patch("backend.orchestrator.session_manager.SemanticTurnDetector", return_value=mock_detector),
        patch("backend.orchestrator.session_manager.ExaminerAgent"),
    ):
        mgr = SessionManager(gateway_api_key="k", gateway_api_secret="s")
        await mgr.start()
        await mgr.create_session(session_id="ses_ap", case_context=case_context)
        resp = await mgr.ingest_and_auto_finalize(session_id="ses_ap", transcript="I was", pause_ms=100)
        assert resp["scorecard"] is None
        assert mgr.get_session("ses_ap").status == SessionStatus.ACTIVE
        await mgr.cleanup()


# ---------------------------------------------------------------------------
# destroy_session / cleanup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_destroy_session_calls_room_exit(mock_gateway, case_context, mock_room):
    """destroy_session calls room.__aexit__ and removes session from dict."""
    with (
        patch("backend.orchestrator.session_manager.Room", return_value=mock_room),
        patch("backend.orchestrator.session_manager.SemanticTurnDetector"),
        patch("backend.orchestrator.session_manager.ExaminerAgent"),
    ):
        mgr = SessionManager(gateway_api_key="k", gateway_api_secret="s")
        await mgr.start()
        await mgr.create_session(session_id="ses_ds", case_context=case_context)
        assert "ses_ds" in mgr._sessions
        await mgr.destroy_session("ses_ds")
        mock_room.__aexit__.assert_awaited_once()
        assert "ses_ds" not in mgr._sessions
        await mgr.cleanup()


@pytest.mark.asyncio
async def test_destroy_session_idempotent(mock_gateway, case_context, mock_room):
    """destroy_session called twice does not raise."""
    with (
        patch("backend.orchestrator.session_manager.Room", return_value=mock_room),
        patch("backend.orchestrator.session_manager.SemanticTurnDetector"),
        patch("backend.orchestrator.session_manager.ExaminerAgent"),
    ):
        mgr = SessionManager(gateway_api_key="k", gateway_api_secret="s")
        await mgr.start()
        await mgr.create_session(session_id="ses_id", case_context=case_context)
        await mgr.destroy_session("ses_id")
        await mgr.destroy_session("ses_id")
        await mgr.cleanup()


# ---------------------------------------------------------------------------
# edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_sessions_filters_by_status(mock_gateway, case_context, mock_room):
    """list_sessions with status= filter returns only matching sessions."""
    with (
        patch("backend.orchestrator.session_manager.Room", return_value=mock_room),
        patch("backend.orchestrator.session_manager.SemanticTurnDetector"),
        patch("backend.orchestrator.session_manager.ExaminerAgent"),
    ):
        mgr = SessionManager(gateway_api_key="k", gateway_api_secret="s")
        await mgr.start()
        await mgr.create_session(session_id="ses_a", case_context=case_context)
        await mgr.create_session(session_id="ses_b", case_context=case_context)
        mgr.pause_session("ses_a")
        active = mgr.list_sessions(status=SessionStatus.ACTIVE)
        paused = mgr.list_sessions(status=SessionStatus.PAUSED)
        assert len(active) == 1
        assert active[0].session_id == "ses_b"
        assert len(paused) == 1
        assert paused[0].session_id == "ses_a"
        await mgr.cleanup()


@pytest.mark.asyncio
async def test_active_session_count(mock_gateway, case_context, mock_room):
    """active_session_count excludes COMPLETED and FAILED sessions."""
    with (
        patch("backend.orchestrator.session_manager.Room", return_value=mock_room),
        patch("backend.orchestrator.session_manager.SemanticTurnDetector"),
        patch("backend.orchestrator.session_manager.ExaminerAgent"),
    ):
        mgr = SessionManager(gateway_api_key="k", gateway_api_secret="s")
        await mgr.start()
        await mgr.create_session(session_id="s1", case_context=case_context)
        await mgr.create_session(session_id="s2", case_context=case_context)
        await mgr.create_session(session_id="s3", case_context=case_context)
        mgr.pause_session("s2")
        await mgr.finalize_scorecard("s3")
        assert mgr.active_session_count == 2
        await mgr.cleanup()


@pytest.mark.asyncio
async def test_get_session_raises_keyerror(mock_gateway, case_context, mock_room):
    """get_session raises KeyError for unknown session."""
    with (
        patch("backend.orchestrator.session_manager.Room", return_value=mock_room),
        patch("backend.orchestrator.session_manager.SemanticTurnDetector"),
        patch("backend.orchestrator.session_manager.ExaminerAgent"),
    ):
        mgr = SessionManager(gateway_api_key="k", gateway_api_secret="s")
        await mgr.start()
        await mgr.create_session(session_id="ses_good", case_context=case_context)
        with pytest.raises(KeyError):
            mgr.get_session("ses_bad")
        await mgr.cleanup()
