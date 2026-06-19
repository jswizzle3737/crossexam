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