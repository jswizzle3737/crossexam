import pytest
import tempfile
import os
from backend.llm_agent.case_ingestor import CaseIngestor, Exhibit, WitnessStatement


def test_ingest_single_file():
    ingestor = CaseIngestor()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("I saw the accused at 8 PM.\nHe was holding a weapon.\n")
        f_path = f.name
    try:
        context = ingestor.ingest([f_path])
        assert len(context.witness_statements) == 2
    finally:
        os.unlink(f_path)


def test_ingest_extracts_exhibits():
    ingestor = CaseIngestor()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("Exhibit 1: Photograph of scene\nExhibit 2: Forensic report\n")
        f_path = f.name
    try:
        context = ingestor.ingest([f_path])
        assert len(context.exhibits) == 2
        assert context.exhibits[0].id == "1"
        assert context.exhibits[1].description == "Forensic report"
    finally:
        os.unlink(f_path)


def test_empty_file():
    ingestor = CaseIngestor()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f_path = f.name
    try:
        context = ingestor.ingest([f_path])
        assert len(context.witness_statements) == 0
        assert len(context.exhibits) == 0
    finally:
        os.unlink(f_path)


def test_contradictions_empty_mvp():
    ingestor = CaseIngestor()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("I saw the car\n")
        f_path = f.name
    try:
        context = ingestor.ingest([f_path])
        assert context.contradictions == []
    finally:
        os.unlink(f_path)