"""Unit tests for Milestone 1: Scaffold, config, keyring isolation, and MockBrain."""

import pytest
from auth.keyring_service import (
    clear_user_secrets,
    delete_user_secret,
    get_user_secret,
    set_user_secret,
)
from config.loader import get_active_profile, load_providers_config, load_settings_config
from models.mock_brain import MockBrain


def test_config_loader_reads_valid_configs():
    """Verify that provider and settings configurations load with expected keys."""
    providers = load_providers_config()
    assert "active_profile" in providers
    assert "profiles" in providers
    assert "local_ollama" in providers["profiles"]
    assert "fallback_order" in providers

    settings = load_settings_config()
    assert "embeddings" in settings
    assert settings["embeddings"]["model"] == "nomic-embed-text"
    assert settings["embeddings"]["run_on_cpu"] is True
    assert "hardware" in settings
    assert "auth" in settings
    assert "jury" in settings


def test_get_active_profile():
    """Verify that get_active_profile returns the active configuration profile."""
    profile = get_active_profile()
    assert profile["name"] == "local_ollama"
    assert profile["model"] == "qwen2.5:7b"
    assert profile["is_local"] is True


def test_keyring_user_isolation():
    """Verify that secrets stored for User A cannot be accessed by User B."""
    user_a = "user-uuid-1111"
    user_b = "user-uuid-2222"

    try:
        # Set secrets for User A
        set_user_secret(user_a, "openai_api_key", "sk-user-a-secret-key")
        set_user_secret(user_a, "colab_token", "colab-token-a")

        # Set different secret for User B
        set_user_secret(user_b, "openai_api_key", "sk-user-b-secret-key")

        # Assert User A receives their own secret
        assert get_user_secret(user_a, "openai_api_key") == "sk-user-a-secret-key"
        assert get_user_secret(user_a, "colab_token") == "colab-token-a"

        # Assert User B receives their own secret and cannot see User A's colab_token
        assert get_user_secret(user_b, "openai_api_key") == "sk-user-b-secret-key"
        assert get_user_secret(user_b, "colab_token") is None

        # Deleting User A's secret does not affect User B
        delete_user_secret(user_a, "openai_api_key")
        assert get_user_secret(user_a, "openai_api_key") is None
        assert get_user_secret(user_b, "openai_api_key") == "sk-user-b-secret-key"
    finally:
        clear_user_secrets(user_a)
        clear_user_secrets(user_b)


def test_mock_brain_recording_and_replies():
    """Verify that MockBrain records calls accurately and returns scripted responses."""
    brain = MockBrain()
    brain.queue_reply({"content": "Scripted test reply 1", "tool_calls": []})

    messages = [{"role": "user", "content": "Explain photosynthesis"}]
    reply = brain.chat(messages=messages, options={"temperature": 0.5})

    assert reply["content"] == "Scripted test reply 1"
    assert len(brain.call_history) == 1
    assert brain.call_history[0]["messages"][0]["content"] == "Explain photosynthesis"
    assert brain.call_history[0]["options"]["temperature"] == 0.5

    # Second call without queued reply uses default generator
    reply2 = brain.chat(messages=[{"role": "user", "content": "Second question"}])
    assert "MockBrain response" in reply2["content"]
    assert len(brain.call_history) == 2

    # Reset clears history
    brain.reset()
    assert len(brain.call_history) == 0
