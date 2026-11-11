"""Unit tests for Milestone 5: Agent loop, approval gate, and per-user action logging."""

import pytest
from auth.context import UserContext
from agent.dispatcher import (
    dispatch_tool,
    register_tool,
)
from agent.orchestrator import run_agent
from models.mock_brain import get_mock_brain
from storage.db import get_action_logs


@pytest.fixture
def agent_test_user(tmp_path):
    """Create a temporary user context for testing agent workflows."""
    data_root = tmp_path / "data"
    return UserContext.create("test-user-agent", "Alex", data_root=data_root)


def test_tool_dispatch_and_safe_error_handling(agent_test_user):
    """Verify that tool errors are returned as clean text instead of crashing execution."""
    # Register a tool that raises an error
    def faulty_tool(user_context, **kwargs):
        raise ValueError("Missing essential parameter in calculation.")

    register_tool("faulty_tool", faulty_tool, {"name": "faulty_tool"})

    result_text, status = dispatch_tool(
        tool_name="faulty_tool",
        tool_args={},
        user_context=agent_test_user,
    )

    assert "Tool error" in result_text
    assert "ValueError" in result_text
    assert status == "error"

    # Verify action log recorded the error
    logs = get_action_logs(agent_test_user)
    assert len(logs) == 1
    assert logs[0]["tool_name"] == "faulty_tool"
    assert logs[0]["approval_status"] == "error"


def test_approval_gate_accept_and_decline(agent_test_user):
    """Verify that sensitive tools pause for approval, and declining returns 'User declined.'."""
    from agent.dispatcher import _TOOL_REGISTRY
    orig_entry = _TOOL_REGISTRY.get("schedule_revision")

    call_tracker = {"executed": False}

    def sensitive_tool(user_context, **kwargs):
        call_tracker["executed"] = True
        return "Schedule exported successfully."

    try:
        # 'schedule_revision' is in requires_confirmation in settings.json
        register_tool("schedule_revision", sensitive_tool, {"name": "schedule_revision"})

        # 1. User declines
        result_decline, status_decline = dispatch_tool(
            tool_name="schedule_revision",
            tool_args={"exam_date": "2026-12-01"},
            user_context=agent_test_user,
            approval_callback=lambda name, args: False,  # User clicks Reject
        )
        assert result_decline == "User declined."
        assert status_decline == "rejected"
        assert call_tracker["executed"] is False

        # 2. User approves
        result_approve, status_approve = dispatch_tool(
            tool_name="schedule_revision",
            tool_args={"exam_date": "2026-12-01"},
            user_context=agent_test_user,
            approval_callback=lambda name, args: True,  # User clicks Approve
        )
        assert result_approve == "Schedule exported successfully."
        assert status_approve == "approved"
        assert call_tracker["executed"] is True
    finally:
        if orig_entry:
            _TOOL_REGISTRY["schedule_revision"] = orig_entry
        elif "schedule_revision" in _TOOL_REGISTRY:
            del _TOOL_REGISTRY["schedule_revision"]


def test_run_agent_loop_with_mock_brain(agent_test_user):
    """Verify the full Goal, Plan, Act, Approve, Log agent execution loop."""
    mock = get_mock_brain()
    mock.reset()

    # Step 1: Brain calls search_notes tool
    mock.queue_reply({
        "content": "I will search your notes for Newton's laws.",
        "tool_calls": [{"name": "mock_search", "args": {"query": "Newton"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    })

    # Step 2: Brain produces final answer after receiving tool result
    mock.queue_reply({
        "content": "Newton's first law states an object remains at rest unless acted on by a net force.",
        "tool_calls": [],
        "usage": {"prompt_tokens": 20, "completion_tokens": 15, "total_tokens": 35},
    })

    # Register mock_search tool
    register_tool(
        "mock_search",
        lambda user_context, query: f"Found note excerpt matching '{query}'.",
        {"name": "mock_search"}
    )

    result = run_agent(
        task="Explain Newton's first law of motion.",
        user_context=agent_test_user,
        options={"profile": "mock"},
        auto_approve=True,
    )

    assert result["status"] == "completed"
    assert "Newton's first law states" in result["final_answer"]
    assert result["iterations"] == 2
    assert len(result["tool_history"]) == 1
    assert result["tool_history"][0]["tool"] == "mock_search"

    # Verify action log contains record of the search tool
    logs = get_action_logs(agent_test_user)
    assert any(log["tool_name"] == "mock_search" for log in logs)


def test_run_agent_iteration_cap(agent_test_user):
    """Verify that run_agent halts cleanly when max_iterations is reached."""
    mock = get_mock_brain()
    mock.reset()

    # Queue repeating tool calls to exceed iteration cap
    for _ in range(5):
        mock.queue_reply({
            "content": "Looping tool call...",
            "tool_calls": [{"name": "dummy_loop_tool", "args": {}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
        })

    register_tool("dummy_loop_tool", lambda user_context: "Loop continue.", {"name": "dummy_loop_tool"})

    result = run_agent(
        task="Infinite loop task",
        max_iterations=3,
        user_context=agent_test_user,
        options={"profile": "mock"},
        auto_approve=True,
    )

    assert result["status"] == "iteration_limit_reached"
    assert result["iterations"] == 3
