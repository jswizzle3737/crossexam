import pytest
from unittest.mock import MagicMock, patch

from backend.llm_agent.examiner import ExaminerAgent, ExaminerConfig


@pytest.fixture
def mock_openai():
    """Stub OpenAI client so tests don't need a real API key."""
    with patch("backend.llm_agent.examiner.OpenAI") as cls:
        instance = MagicMock()
        cls.return_value = instance

        # Break auto-vivification chain: use explicit intermediate references
        # so that `choices[0].message.content` returns the same configured object
        # on every access.
        response_mock = MagicMock()
        response_mock.choices = [MagicMock(message=MagicMock(content="Expected question?"))]
        instance.chat.completions.create.return_value = response_mock

        yield instance


def test_examiner_creates_question(mock_openai):
    """Synchronous smoke test — calls are now async but ExaminerAgent.__init__ is not."""
    agent = ExaminerAgent()
    q = agent.generate_question("I don't recall exactly", {})
    assert isinstance(q, str)
    assert len(q) > 5


def test_examiner_loads_prompt(mock_openai):
    agent = ExaminerAgent()
    assert "Crown prosecutor" in agent._system_prompt


def test_examiner_tracks_history(mock_openai):
    agent = ExaminerAgent()
    agent.generate_question("I was there", {})
    agent.generate_question("No, I didn't see him", {})
    assert len(agent._conversation_history) == 2


def test_log_impeachment(mock_openai):
    agent = ExaminerAgent()
    result = agent.log_impeachment("I saw the car", "I did not see any car")
    assert result["type"] == "impeachment"
    assert "car" in result["witness_statement"]


@pytest.mark.asyncio
async def test_generate_question_calls_openai(mock_openai):
    """Verify OpenAI client is called with correct arguments."""
    mock_openai.chat.completions.create.return_value.choices[0].message.content = \
        "Did you not see the traffic light?"

    agent = ExaminerAgent()
    question = agent.generate_question("I don't recall", {"key": "value"})

    assert question == "Did you not see the traffic light?"
    mock_openai.chat.completions.create.assert_called_once()
    # Inspect call_args_list to avoid MagicMock auto-vivification on call_kwargs
    call_args, call_kwargs = mock_openai.chat.completions.create.call_args
    assert call_kwargs["model"] == "openai/gpt-4o-mini"
    assert call_kwargs["temperature"] == 0.6
    assert call_kwargs["max_tokens"] == 150
    # System prompt + history + user message
    assert len(call_kwargs["messages"]) >= 2