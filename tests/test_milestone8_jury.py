"""Unit tests for Milestone 8: 6-Agent Jury Debate, blind review label stripping, and quick mode."""

import pytest
from auth.context import UserContext
from agent.dispatcher import dispatch_tool
from agent.jury import execute_jury_debate, strip_role_labels
from models.mock_brain import get_mock_brain
from storage.vector_store import add_document_chunks
from tools.run_jury import run_jury


@pytest.fixture
def jury_user(tmp_path):
    """Create a temporary user context with sample indexed physics notes."""
    data_root = tmp_path / "data"
    user = UserContext.create("test-jury-user", "Aria", data_root=data_root)

    # Index sample note for retrieval
    chunks = [
        {
            "id": "p1",
            "filename": "quantum.pdf",
            "page": 42,
            "topic": "Photoelectric Effect",
            "text": "The photoelectric effect demonstrates the particle nature of light, where photon energy equals h*nu.",
        }
    ]
    add_document_chunks(user, "Physics", chunks)
    return user


def test_strip_role_labels():
    """Verify that role labels are stripped to Candidate Answer A..F for blind peer reviews."""
    round1 = {
        "explainer": "Answer from explainer.",
        "rigorous_expert": "Answer from expert.",
        "skeptic": "Answer from skeptic.",
        "exam_coach": "Answer from coach.",
        "example_builder": "Answer from builder.",
        "fact_checker": "Answer from fact checker.",
    }
    anonymous, label_to_role = strip_role_labels(round1)

    assert len(anonymous) == 6
    # Check that persona names are not in keys
    for key in anonymous.keys():
        assert "Candidate Answer" in key
        assert "explainer" not in key
        assert "expert" not in key
        assert "skeptic" not in key

    # Check mapping
    assert len(label_to_role) == 6


def test_quick_mode_execution(jury_user):
    """Verify quick mode returns a single direct answer with citations using MockBrain."""
    mock = get_mock_brain()
    mock.reset()
    mock.queue_reply({
        "content": "In quick mode, the photoelectric effect proves light quantization.",
        "tool_calls": [],
        "usage": {"prompt_tokens": 15, "completion_tokens": 10, "total_tokens": 25},
    })

    result = execute_jury_debate(
        question="What does the photoelectric effect prove?",
        subject="Physics",
        user_context=jury_user,
        mode="quick",
        profile_name="mock",
    )

    assert result["mode"] == "quick"
    assert "In quick mode" in result["final_answer"]
    assert any("quantum.pdf" in c for c in result["citations"])


def test_full_jury_debate_rounds(jury_user):
    """Verify full 6-agent debate: Round 1 answers, Round 2 blind critiques, and Judge synthesis."""
    mock = get_mock_brain()
    mock.reset()

    # Dynamic reply generator for MockBrain so each agent call gets a distinct response
    def dynamic_mock(messages):
        user_text = messages[-1].get("content", "")
        system_text = messages[0].get("content", "") if messages else ""

        if "Chief Judicial Synthesizer" in system_text:
            return {
                "content": "Judge Verdict: The photoelectric effect definitively establishes light quantization. Cited from quantum.pdf p.42.",
                "tool_calls": [],
                "usage": {"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70},
            }
        elif "candidate answers" in user_text:
            return {
                "content": "Critique: Candidate Answer A provides clear intuition, Candidate B offers exact formulas.",
                "tool_calls": [],
                "usage": {"prompt_tokens": 20, "completion_tokens": 15, "total_tokens": 35},
            }
        else:
            return {
                "content": f"Independent analysis from persona addressing: {user_text[:30]}",
                "tool_calls": [],
                "usage": {"prompt_tokens": 15, "completion_tokens": 10, "total_tokens": 25},
            }

    mock.set_reply_generator(dynamic_mock)

    jury_result = execute_jury_debate(
        question="How does photon frequency affect electron kinetic energy?",
        subject="Physics",
        user_context=jury_user,
        mode="jury",
        profile_name="mock",
    )

    assert jury_result["mode"] == "jury"
    assert len(jury_result["round1_answers"]) == 6
    assert len(jury_result["blind_critiques"]) == 6
    assert "Judge Verdict:" in jury_result["final_answer"]
    assert any("quantum.pdf" in c for c in jury_result["citations"])


def test_run_jury_tool_dispatch(jury_user):
    """Verify run_jury tool dispatch through agent dispatcher."""
    mock = get_mock_brain()
    mock.reset()
    mock.queue_reply({
        "content": "Direct quick response via dispatcher tool.",
        "tool_calls": [],
        "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
    })

    tool_output, status = dispatch_tool(
        tool_name="run_jury",
        tool_args={"question": "Explain work function", "subject": "Physics", "mode": "quick"},
        user_context=jury_user,
        profile_name="mock",
    )

    assert status == "auto"
    assert "=== StudyAssist Answer (Quick Mode) ===" in tool_output
    assert "Direct quick response via dispatcher tool." in tool_output
