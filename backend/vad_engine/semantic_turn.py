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
    FILLER_WORDS = {
        "uh", "um", "like", "you know", "i mean", "well", "actually",
        "basically", "literally", "right?", "see", "look", "listen",
    }
    TRAILING_CONJUNCTIONS = {
        "and", "but", "or", "so", "because", "however",
    }

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