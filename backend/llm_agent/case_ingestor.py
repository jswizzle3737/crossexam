"""Ingests criminal case files and extracts structured evidence / contradictions."""

from dataclasses import dataclass, field
from typing import List, Optional
import re


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
        with open(path) as f:
            return f.read()

    def _extract_statements(self, text: str) -> List[WitnessStatement]:
        lines = [l for l in text.split("\n") if l.strip()]
        return [WitnessStatement(witness_id="unknown", statement_text=l, source="uploaded") for l in lines]

    def _extract_exhibits(self, text: str, source: str) -> List[Exhibit]:
        exhibits = []
        for match in re.finditer(r"Exhibit\s+(\d+)\s*[:\-–]\s*(.+)", text, re.IGNORECASE):
            exhibits.append(Exhibit(id=match.group(1), description=match.group(2).strip(), source_file=source))
        return exhibits

    def _find_contradictions(self, statements: List[WitnessStatement]) -> List[dict]:
        # MVP: placeholder — LLM-based detection in v2
        return []