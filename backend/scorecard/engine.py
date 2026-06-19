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
    credibility_risk: str = "unknown"
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
        self._recalculate_risk()

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