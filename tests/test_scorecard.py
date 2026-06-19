import pytest
from backend.scorecard.engine import ScorecardBuilder, ScorecardEntry, Scorecard


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


def test_moderate_risk_one_critical():
    builder = ScorecardBuilder("session-3")
    builder.add_entry(ScorecardEntry(
        type="evasive", description="Evasive answer to key question",
        severity="critical", timestamp_sec=15.0, witness_answer="I'm not sure"
    ))
    assert builder.build().credibility_risk == "moderate"


def test_low_risk_minor_entries():
    builder = ScorecardBuilder("session-4")
    builder.add_entry(ScorecardEntry(
        type="evasive", description="Minor evasion",
        severity="minor", timestamp_sec=5.0, witness_answer="I think so"
    ))
    assert builder.build().credibility_risk == "low"


def test_scorecard_properties():
    card = Scorecard(session_id="test", duration_sec=120.0)
    assert card.impeachment_count == 0
    assert card.total_contradictions == 0