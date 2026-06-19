"""Adversarial Crown prosecutor LLM agent."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

from openai import OpenAI

from backend.config import settings


@dataclass
class ExaminerConfig:
    model: str = "openai/gpt-4o-mini"
    temperature: float = 0.6
    max_tokens: int = 150
    system_prompt_path: str = str(Path(__file__).parent / "prompts" / "examiner_system.txt")


class ExaminerAgent:
    def __init__(self, config: Optional[ExaminerConfig] = None):
        self.config = config or ExaminerConfig()
        self._system_prompt = self._load_prompt()
        self._conversation_history: list[dict] = []

        # OpenRouter client — base_url set so SDK works with any OpenAI-compatible endpoint
        self._client = OpenAI(
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
        )

    def _load_prompt(self) -> str:
        with open(self.config.system_prompt_path) as f:
            return f.read()

    def generate_question(self, transcript: str, case_context: dict) -> str:
        """Generate the next cross-examination question based on last witness answer."""
        messages: list[dict] = [
            {"role": "system", "content": self._system_prompt},
            *self._conversation_history[-10:],
            {"role": "user", "content": f"Witness says: {transcript}\nCase context: {case_context}"}
        ]
        response = self._client.chat.completions.create(
            model=settings.openrouter_model,
            messages=messages,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
        )
        question = response.choices[0].message.content or ""
        self._conversation_history.append({"role": "assistant", "content": question})
        return question

    async def generate_question_async(self, transcript: str, case_context: dict) -> str:
        """Async wrapper — runs the sync LLM call in a thread pool to avoid blocking the event loop."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            self.generate_question,
            transcript,
            case_context,
        )

    def log_impeachment(self, transcript: str, prior_statement: str) -> dict:
        """Record a contradiction for the scorecard."""
        return {
            "type": "impeachment",
            "witness_statement": transcript,
            "prior_statement": prior_statement,
            "timestamp": None,
        }