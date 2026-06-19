"""Adversarial Crown prosecutor LLM agent."""

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ExaminerConfig:
    model: str = "gpt-4"
    temperature: float = 0.6
    max_tokens: int = 150
    system_prompt_path: str = str(Path(__file__).parent / "prompts" / "examiner_system.txt")


class ExaminerAgent:
    def __init__(self, config: Optional[ExaminerConfig] = None):
        self.config = config or ExaminerConfig()
        self._system_prompt = self._load_prompt()
        self._conversation_history: list[dict] = []

    def _load_prompt(self) -> str:
        with open(self.config.system_prompt_path) as f:
            return f.read()

    def generate_question(self, transcript: str, case_context: dict) -> str:
        """Generate the next cross-examination question based on last witness answer."""
        messages = [
            {"role": "system", "content": self._system_prompt},
            *self._conversation_history[-10:],
            {"role": "user", "content": f"Witness says: {transcript}\nCase context: {case_context}"}
        ]
        # LLM call placeholder — swap for real inference provider
        question = "I put it to you that you did not see the accused at 8:15 PM."
        self._conversation_history.append({"role": "assistant", "content": question})
        return question

    def log_impeachment(self, transcript: str, prior_statement: str) -> dict:
        """Record a contradiction for the scorecard."""
        return {
            "type": "impeachment",
            "witness_statement": transcript,
            "prior_statement": prior_statement,
            "timestamp": None,
        }