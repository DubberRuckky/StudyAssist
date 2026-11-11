"""Service for securely storing per-user API keys and tokens in the OS keyring."""

import logging
from typing import Optional

try:
    import keyring
except ImportError:
    keyring = None

logger = logging.getLogger(__name__)

# Fallback in-memory storage for test suites or headless environments where keyring backend is unavailable
_IN_MEMORY_VAULT: dict[str, dict[str, str]] = {}


def _build_service_name(user_id: str) -> str:
    """Build a unique OS keyring service identifier including the user id."""
    return f"StudyAssist_User_{user_id}"


def get_user_secret(user_id: str, key_name: str) -> Optional[str]:
    """Retrieve an API key or token for a specific user from the OS keyring."""
    service_name = _build_service_name(user_id)
    if keyring is not None:
        try:
            val = keyring.get_password(service_name, key_name)
            if val is not None:
                return val
        except Exception as error:
            logger.warning("OS Keyring read failed, falling back to memory vault: %s", error)
    return _IN_MEMORY_VAULT.get(user_id, {}).get(key_name)


def set_user_secret(user_id: str, key_name: str, secret_value: str) -> None:
    """Save an API key or token for a specific user into the OS keyring."""
    service_name = _build_service_name(user_id)
    if user_id not in _IN_MEMORY_VAULT:
        _IN_MEMORY_VAULT[user_id] = {}
    _IN_MEMORY_VAULT[user_id][key_name] = secret_value

    if keyring is not None:
        try:
            keyring.set_password(service_name, key_name, secret_value)
        except Exception as error:
            logger.warning("OS Keyring write failed, stored in memory vault: %s", error)


def delete_user_secret(user_id: str, key_name: str) -> None:
    """Delete a stored API key or token for a specific user from the OS keyring."""
    service_name = _build_service_name(user_id)
    if user_id in _IN_MEMORY_VAULT and key_name in _IN_MEMORY_VAULT[user_id]:
        del _IN_MEMORY_VAULT[user_id][key_name]

    if keyring is not None:
        try:
            keyring.delete_password(service_name, key_name)
        except Exception:
            pass  # Key might not exist in keyring


def clear_user_secrets(user_id: str) -> None:
    """Clear all cached secrets for a user upon account deletion or logout."""
    if user_id in _IN_MEMORY_VAULT:
        del _IN_MEMORY_VAULT[user_id]
