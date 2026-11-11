"""Unit tests for Milestone 9: Gradio web interface, 127.0.0.1 localhost binding, and view states."""

import inspect
import gradio as gr
import pytest

from app import main
from ui.dashboard import create_app


def test_gradio_app_initialization():
    """Verify that create_app builds a complete Gradio Blocks instance without errors."""
    demo = create_app()
    assert isinstance(demo, gr.Blocks)
    assert demo.title == "StudyAssist — Agentic AI Study Assistant"


def test_network_safety_binding_localhost_only():
    """Verify that the application launch signature strictly binds to 127.0.0.1 and prohibits public sharing."""
    import app
    source_code = inspect.getsource(app.main)

    # Check strictly that 127.0.0.1 is specified
    assert 'server_name="127.0.0.1"' in source_code
    # Check that share=False is explicitly enforced
    assert "share=False" in source_code
    # Ensure 0.0.0.0 is not used
    assert "0.0.0.0" not in source_code


def test_all_six_tools_registered_on_app_import():
    """Verify that importing app registers all six canonical tools in the dispatcher."""
    import app  # noqa: F401
    from agent.dispatcher import _TOOL_REGISTRY

    expected_tools = {
        "ingest_material",
        "search_notes",
        "run_jury",
        "generate_quiz",
        "schedule_revision",
        "track_progress",
    }
    registered = set(_TOOL_REGISTRY.keys())
    assert expected_tools.issubset(registered), f"Missing tools: {expected_tools - registered}"
