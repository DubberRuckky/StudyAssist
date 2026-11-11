"""High-level authentication service coordinating database, context, and sessions."""

from pathlib import Path
from typing import Optional, Tuple

from auth.context import UserContext
from auth.database import (
    authenticate_user,
    change_password,
    create_user,
    delete_user_account,
    reset_password_with_recovery_key,
)
from auth.hasher import generate_recovery_key
from auth.keyring_service import clear_user_secrets
from auth.session import create_session, end_session, register_logout_hook, validate_session

# Hook up keyring cache clearance on logout
register_logout_hook(clear_user_secrets)


def register_account(
    username: str,
    password: str,
    confirm_password: str,
    db_path: Optional[Path] = None,
    data_root: Optional[Path] = None,
) -> Tuple[bool, str, Optional[str]]:
    """Register a new user account, return status, message, and one-time recovery key."""
    if password != confirm_password:
        return False, "Passwords do not match.", None

    recovery_key = generate_recovery_key()
    success, msg, user_uuid = create_user(
        username=username,
        password=password,
        recovery_key=recovery_key,
        db_path=db_path,
    )

    if not success or not user_uuid:
        return False, msg, None

    # Pre-initialize user directories
    UserContext.create(user_id=user_uuid, username=username, data_root=data_root)

    return True, "Account created successfully.", recovery_key


def login_account(
    username: str,
    password: str,
    db_path: Optional[Path] = None,
    data_root: Optional[Path] = None,
) -> Tuple[bool, str, Optional[str], Optional[UserContext]]:
    """Authenticate credentials and establish an active in-memory user session."""
    success, msg, user_info = authenticate_user(
        username=username,
        password=password,
        db_path=db_path,
    )

    if not success or not user_info:
        return False, msg, None, None

    context = UserContext.create(
        user_id=user_info["id"],
        username=user_info["username"],
        display_name=user_info["display_name"],
        data_root=data_root,
    )
    session_token = create_session(context)
    return True, "Login successful.", session_token, context


def logout_account(session_token: Optional[str]) -> Tuple[bool, str]:
    """Terminate the user session and clear per-user in-memory resources."""
    if not session_token:
        return False, "No active session."
    end_session(session_token)
    return True, "Logged out successfully."


def change_account_password(
    user_id: str,
    current_password: str,
    new_password: str,
    confirm_password: str,
    db_path: Optional[Path] = None,
) -> Tuple[bool, str]:
    """Change an authenticated user's password."""
    if new_password != confirm_password:
        return False, "New passwords do not match."

    return change_password(
        user_id=user_id,
        current_password=current_password,
        new_password=new_password,
        db_path=db_path,
    )


def delete_account(
    user_id: str,
    password: str,
    session_token: Optional[str] = None,
    db_path: Optional[Path] = None,
    data_root: Optional[Path] = None,
) -> Tuple[bool, str]:
    """Delete a user account, wipe database row, purge user directory, and clear secrets."""
    # Create context to locate folder
    context = UserContext.create(user_id=user_id, username="", data_root=data_root)

    # First verify password and remove from auth.db
    success, msg = delete_user_account(user_id=user_id, password=password, db_path=db_path)
    if not success:
        return False, msg

    # Terminate active session if provided
    if session_token:
        end_session(session_token)

    # Clear stored OS keyring secrets
    clear_user_secrets(user_id)

    # Purge entire user directory (data/users/<user_id>/)
    context.purge_user_data()

    return True, "Account and all associated study materials permanently deleted."
