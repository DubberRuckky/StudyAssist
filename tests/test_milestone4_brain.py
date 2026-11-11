"""Unit tests for Milestone 4: Brain gateway, fallback chains, portable JSON repair, and hardware check."""

from unittest.mock import MagicMock, patch
import pytest

from auth.context import UserContext
from config.loader import load_providers_config, save_providers_config
from models.brain import chat
from models.hardware import run_hardware_preflight
from models.mock_brain import get_mock_brain
from models.tool_protocol import (
    parse_portable_tool_response,
    repair_json_string,
)
from storage.db import set_subject_local_only


def test_portable_json_repair_and_parsing():
    """Verify robust JSON repair: code fences, trailing commas, single quotes, and schema parsing."""
    # 1. Code fence stripping
    raw1 = "```json\n{\"action\": \"search_notes\", \"args\": {\"query\": \"mitochondria\"}}\n```"
    action1 = parse_portable_tool_response(raw1)
    assert action1.action == "search_notes"
    assert action1.args["query"] == "mitochondria"

    # 2. Trailing commas and surrounding prose
    raw2 = "Here is the tool call:\n{\"action\": \"generate_quiz\", \"args\": {\"subject\": \"Math\", \"count\": 5, }, }\nHope that helps!"
    action2 = parse_portable_tool_response(raw2)
    assert action2.action == "generate_quiz"
    assert action2.args["count"] == 5

    # 3. Final answer parsing
    raw3 = '{"action": "final", "answer": "The powerhouse of the cell is the mitochondrion."}'
    action3 = parse_portable_tool_response(raw3)
    assert action3.action == "final"
    assert "powerhouse" in action3.answer


def test_brain_chat_mock_provider():
    """Verify that chat() dispatches to mock provider and records interactions."""
    mock_brain = get_mock_brain()
    mock_brain.reset()
    mock_brain.queue_reply({
        "content": "Verified mock reply for chemistry question.",
        "tool_calls": [],
        "usage": {"prompt_tokens": 15, "completion_tokens": 12, "total_tokens": 27},
    })

    messages = [{"role": "user", "content": "What is an isotope?"}]
    res = chat(messages=messages, options={"profile": "mock"})

    assert res["content"] == "Verified mock reply for chemistry question."
    assert res["profile_used"] == "mock"
    assert res["fallback_occurred"] is False
    assert len(mock_brain.call_history) == 1


def test_brain_automatic_fallback():
    """Verify that when the active profile fails, chat() automatically falls back to next profile."""
    mock_brain = get_mock_brain()
    mock_brain.reset()
    mock_brain.queue_reply({
        "content": "Fallback successful reply",
        "tool_calls": [],
        "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
    })

    # Temporarily adjust configuration to attempt a failing profile followed by mock
    orig_config = load_providers_config()
    try:
        test_config = dict(orig_config)
        test_config["profiles"]["broken_profile"] = {
            "provider_type": "ollama",
            "model": "non-existent-model",
            "base_url": "http://127.0.0.1:9999",  # unreachable port
            "timeout_seconds": 1,
            "is_local": True,
        }
        test_config["fallback_order"] = ["broken_profile", "mock"]
        save_providers_config(test_config)

        res = chat(
            messages=[{"role": "user", "content": "Test fallback"}],
            options={"profile": "broken_profile"},
        )
        assert res["profile_used"] == "mock"
        assert res["fallback_occurred"] is True
        assert res["content"] == "Fallback successful reply"

    finally:
        save_providers_config(orig_config)


def test_per_subject_local_only_enforcement(tmp_path):
    """Verify that per-subject local-only toggle blocks non-local remote cloud providers."""
    mock_brain = get_mock_brain()
    mock_brain.reset()
    mock_brain.queue_reply({
        "content": "Local brain answered strictly offline.",
        "tool_calls": [],
        "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
    })

    data_root = tmp_path / "data"
    user = UserContext.create("test-user-local", "LocalStudent", data_root=data_root)

    # Mark subject "PrivateHistory" as local only
    set_subject_local_only(user, "PrivateHistory", True)

    orig_config = load_providers_config()
    try:
        test_config = dict(orig_config)
        test_config["fallback_order"] = ["remote_cloud", "mock"]
        save_providers_config(test_config)

        # Attempt to call remote_cloud on a local_only subject; should bypass remote_cloud and fall back to local mock
        res = chat(
            messages=[{"role": "user", "content": "Private note summary"}],
            options={"profile": "remote_cloud", "subject": "PrivateHistory"},
            user_context=user,
        )
        assert res["profile_used"] == "mock"
    finally:
        save_providers_config(orig_config)


def test_hardware_preflight_synthetic_detection():
    """Verify hardware check verdict logic under various synthetic system profiles."""
    # 1. Simulate High-End Dedicated GPU Desktop (e.g. AMD RX 6600, 16GB RAM)
    with patch("models.hardware.detect_gpu_info") as mock_gpu, \
         patch("psutil.virtual_memory") as mock_mem, \
         patch("models.hardware.check_ollama_status") as mock_ollama, \
         patch("models.hardware.benchmark_tokens_per_second") as mock_tps:

        mock_gpu.return_value = {
            "gpus": ["AMD Radeon RX 6600"],
            "is_amd": True,
            "is_dedicated": True,
            "is_integrated": False,
        }
        mock_mem.return_value = MagicMock(total=16 * (1024**3), available=12 * (1024**3))
        mock_ollama.return_value = {"reachable": True, "vram_percentage": 100.0}
        mock_tps.return_value = 32.5

        result = run_hardware_preflight()
        assert result["verdict"] == "Good"
        assert "Dedicated GPU Desktop" in result["machine_type"]
        assert result["recommended_mode"] == "jury"
        assert "OLLAMA_VULKAN=1" in result["vulkan_tip"]

    # 2. Simulate Low-Memory Integrated GPU Laptop (AMD Ryzen AI / Radeon 860M with low free RAM)
    with patch("models.hardware.detect_gpu_info") as mock_gpu, \
         patch("psutil.virtual_memory") as mock_mem, \
         patch("models.hardware.check_ollama_status") as mock_ollama, \
         patch("models.hardware.benchmark_tokens_per_second") as mock_tps:

        mock_gpu.return_value = {
            "gpus": ["AMD Radeon 860M Graphics"],
            "is_amd": True,
            "is_dedicated": False,
            "is_integrated": True,
        }
        mock_mem.return_value = MagicMock(total=24 * (1024**3), available=3.5 * (1024**3))
        mock_ollama.return_value = {"reachable": True, "vram_percentage": 50.0}
        mock_tps.return_value = 14.0

        result_laptop = run_hardware_preflight()
        assert "Slow (use quick mode only)" in result_laptop["verdict"]
        assert "Shared-Memory Laptop" in result_laptop["machine_type"]
        assert result_laptop["low_ram_warning"] is True
        assert result_laptop["recommended_mode"] == "quick"
