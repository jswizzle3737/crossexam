import pytest
from backend.replay.segment_store import SegmentStore, AudioSegment


def test_add_and_retrieve():
    store = SegmentStore()
    seg = AudioSegment(
        segment_id="seg-1",
        session_id="s1",
        start_sec=0.0,
        end_sec=5.0,
        transcript="I saw nothing",
    )
    store.add_segment(seg)
    result = store.get_segments("s1")
    assert len(result) == 1
    assert result[0].segment_id == "seg-1"


def test_filter_by_label():
    store = SegmentStore()
    store.add_segment(
        AudioSegment("s1", "s1", 0, 5, "answer 1", label="weak_answer")
    )
    store.add_segment(
        AudioSegment("s2", "s1", 5, 10, "answer 2", label="strong_answer")
    )
    store.add_segment(
        AudioSegment("s3", "s1", 10, 15, "answer 3", label="weak_answer")
    )
    weak = store.get_segments("s1", label="weak_answer")
    assert len(weak) == 2


def test_empty_session():
    store = SegmentStore()
    assert store.get_segments("nonexistent") == []


def test_sorted_by_start_time():
    store = SegmentStore()
    store.add_segment(AudioSegment("s3", "s1", 10, 15, "third"))
    store.add_segment(AudioSegment("s1", "s1", 0, 5, "first"))
    store.add_segment(AudioSegment("s2", "s1", 5, 10, "second"))
    results = store.get_segments("s1")
    assert [s.segment_id for s in results] == ["s1", "s2", "s3"]


def test_multi_session_isolation():
    store = SegmentStore()
    store.add_segment(AudioSegment("s1", "session-a", 0, 5, "a1"))
    store.add_segment(AudioSegment("s2", "session-b", 0, 5, "b1"))
    assert len(store.get_segments("session-a")) == 1
    assert len(store.get_segments("session-b")) == 1