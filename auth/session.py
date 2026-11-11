"""In-memory session manager tracking active user sessions and idle timeouts."""

import secrets
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from auth.context import UserContext
from config.loader import load_settings_config

# Map of session_token -> {"context": UserContext, "last_active": float}
_ACTIVE_SESSIONS: Dict[str, Dict[str, Any]] = {}

# List of cleanup callbacks triggered when a user logs out (e.g. clearing in-memory caches)
_LOGOUT_HOOKS: List[Callable[[str], None]] = []


def register_logout_hook(callback: Callable[[str], None]) -> None:
    """Register a callback function to be executed when a user session terminates."""
    _LOGOUT_HOOKS.append(callback)


def get_session_timeout_seconds() -> int:
    """Retrieve session timeout in seconds from settings.json."""
    try:
        minutes = load_settings_config().get("auth", {}).get("session_timeout_minutes", 60)
        return int(minutes * 60)
    except Exception:
        return 3600


def create_session(context: UserContext) -> str:
    """Generate a high-entropy 256-bit session token and register the active user session."""
    token = secrets.token_hex(32)
    _ACTIVE_SESSIONS[token] = {
        "context": context,
        "last_active": time.time(),
    }
    return token


def validate_session(token: Optional[str]) -> Tuple[bool, Optional[UserContext], str]:
    """Validate a session token, check idle expiration, and update activity timestamp."""
    if not token or token not in _ACTIVE_SESSIONS:
        return False, None, "No active session or session invalid."

    session_info = _ACTIVE_SESSIONS[token]
    now = time.time()
    idle_limit = get_session_timeout_seconds()

    if now - session_info["last_active"] > idle_limit:
        # Expired session
        user_id = session_info["context"].user_id
        end_session(token)
        return False, None, "Session has expired due to inactivity. Please log in again."

    # Touch session activity
    session_info["last_active"] = now
    return True, session_info["context"], "Session valid."


def end_session(token: Optional[str]) -> None:
    """Terminate an active session and invoke all registered cache clearance hooks."""
    if not token or token not in _ACTIVE_SESSIONS:
        return

    session_data = _ACTIVE_SESSIONS.pop(token)
    user_id = session_data["context"].user_id

    # Execute all registered logout cleanup hooks for this user
    for hook in _LOGOUT_HOOKS:
        try:
            hook(user_id)
        except Exception:
            pass


def clear_all_sessions() -> None:
    """Flush all active in-memory sessions (used for test teardown)."""
    _ACTIVE_SESSIONS.clear()
