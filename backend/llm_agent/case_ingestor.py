"""Ingests criminal case files and extracts structured evidence / contradictions."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List
import re


MAX_CASE_FILE_BYTES = 10 * 1024 * 1024


@dataclass
class Exhibit:
    id: str
    description: str
    source_file: str


@dataclass
class WitnessStatement:
    witness_id: str
    statement_text: str
    source: str


@dataclass
class CaseContext:
    case_id: str
    exhibits: List[Exhibit] = field(default_factory=list)
    witness_statements: List[WitnessStatement] = field(default_factory=list)
    contradictions: List[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "exhibits": [
                {"id": e.id, "description": e.description, "source_file": e.source_file}
                for e in self.exhibits
            ],
            "witness_statements": [
                {"witness_id": s.witness_id, "statement_text": s.statement_text, "source": s.source}
                for s in self.witness_statements
            ],
            "contradictions": self.contradictions,
        }


class CaseIngestor:
    def ingest(self, file_paths: List[str]) -> CaseContext:
        """Parse uploaded case files into structured context."""
        context = CaseContext(case_id="auto")
        for path in file_paths:
            text = self._read_file(path)
            extracted = self._extract_statements(text)
            context.witness_statements.extend(extracted)
            exhibits = self._extract_exhibits(text, path)
            context.exhibits.extend(exhibits)
        context.contradictions = self._find_contradictions(context.witness_statements)
        return context

    def _read_file(self, path: str) -> str:
        target = Path(path)
        if not target.is_file():
            raise FileNotFoundError(f"Case file not found: {target.name}")
        if target.stat().st_size > MAX_CASE_FILE_BYTES:
            raise ValueError("Case file exceeds the 10 MB processing limit")
        return target.read_text(encoding="utf-8", errors="replace")

    def _extract_statements(self, text: str) -> List[WitnessStatement]:
        lines = [l for l in text.split("\n") if l.strip()]
        return [WitnessStatement(witness_id="unknown", statement_text=l, source="uploaded") for l in lines]

    def _extract_exhibits(self, text: str, source: str) -> List[Exhibit]:
        exhibits = []
        for match in re.finditer(r"Exhibit\s+(\d+)\s*[:\-–]\s*(.+)", text, re.IGNORECASE):
            exhibits.append(Exhibit(id=match.group(1), description=match.group(2).strip(), source_file=Path(source).name))
        return exhibits

    def _find_contradictions(self, statements: List[WitnessStatement]) -> List[dict]:
        # MVP: placeholder — LLM-based detection in v2
        return []
