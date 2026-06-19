import pytest
from backend.llm_agent.examiner import ExaminerAgent, ExaminerConfig


def test_examiner_creates_question():
    agent = ExaminerAgent()
    q = agent.generate_question("I don't recall exactly", {})
    assert isinstance(q, str)
    assert len(q) > 5


def test_examiner_loads_prompt():
    agent = ExaminerAgent()
    assert "Crown prosecutor" in agent._system_prompt


def test_examiner_tracks_history():
    agent = ExaminerAgent()
    agent.generate_question("I was there", {})
    agent.generate_question("No, I didn't see him", {})
    assert len(agent._conversation_history) == 2


def test_log_impeachment():
    agent = ExaminerAgent()
    result = agent.log_impeachment("I saw the car", "I did not see any car")
    assert result["type"] == "impeachment"
    assert "car" in result["witness_statement"]