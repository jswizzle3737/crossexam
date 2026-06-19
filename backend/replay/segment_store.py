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
    label: Optional[str] = None


class SegmentStore:
    def __init__(self):
        self._segments: Dict[str, List[AudioSegment]] = {}

    def add_segment(self, segment: AudioSegment):
        self._segments.setdefault(segment.session_id, []).append(segment)

    def get_segments(
        self, session_id: str, label: Optional[str] = None
    ) -> List[AudioSegment]:
        results = self._segments.get(session_id, [])
        if label:
            results = [s for s in results if s.label == label]
        return sorted(results, key=lambda s: s.start_sec)