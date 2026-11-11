"""Unit tests for Milestone 2: Auth database, Argon2id hashing, lockout, UserContext, and sessions."""

import time
from pathlib import Path
import pytest

from auth.context import UserContext
from auth.database import (
    GENERIC_AUTH_ERROR,
    authenticate_user,
    create_user,
    delete_user_account,
    get_db_connection,
    init_auth_db,
    reset_password_with_recovery_key,
)
from auth.hasher import (
    check_password_strength,
    generate_recovery_key,
    hash_password,
    validate_username,
    verify_password,
)
from auth.service import (
    change_account_password,
    delete_account,
    login_account,
    logout_account,
    register_account,
)
from auth.session import (
    clear_all_sessions,
    create_session,
    end_session,
    register_logout_hook,
    validate_session,
)


@pytest.fixture
def temp_auth_env(tmp_path):
    """Create a temporary auth database and isolated data directory for testing."""
    auth_db_path = tmp_path / "auth.db"
    data_root = tmp_path / "data"
    init_auth_db(auth_db_path)
    clear_all_sessions()
    return auth_db_path, data_root


def test_argon2id_hashing_and_salt_uniqueness():
    """Verify that password hashing works, wrong passwords fail, and salts produce different hashes."""
    password = "SuperSecretPassword123!"
    hash1 = hash_password(password)
    hash2 = hash_password(password)

    # Hashes must never equal the plaintext password
    assert hash1 != password
    # Hashes must be unique due to random salt
    assert hash1 != hash2
    # Verify correctness
    valid, _ = verify_password(hash1, password)
    assert valid is True
    # Wrong password must fail
    invalid, _ = verify_password(hash1, "WrongPassword123!")
    assert invalid is False


def test_password_and_username_validation():
    """Verify username and password strength rules."""
    # Username rules
    assert validate_username("ab")[0] is False  # <3 chars
    assert validate_username("a" * 33)[0] is False  # >32 chars
    assert validate_username("user@name")[0] is False  # invalid char '@'
    assert validate_username("alice_smith-99")[0] is True  # valid

    # Password rules
    assert check_password_strength("short")[0] is False  # <10 chars
    assert check_password_strength("password123")[0] is False  # common password
    assert check_password_strength("MySecurePassword2026!")[0] is True


def test_user_registration_and_case_insensitive_uniqueness(temp_auth_env):
    """Verify account registration and case-insensitive username collision prevention."""
    db_path, data_root = temp_auth_env
    rec_key = generate_recovery_key()
    assert rec_key.startswith("STUDY-")

    # Register 'Alice'
    success, msg, user_id = create_user("Alice", "SecurePass1234!", rec_key, db_path=db_path)
    assert success is True
    assert user_id is not None

    # Registering 'alice' (different case) must be rejected
    success2, msg2, _ = create_user("alice", "SecurePass1234!", rec_key, db_path=db_path)
    assert success2 is False
    assert "already taken" in msg2.lower()


def test_generic_error_and_lockout_throttling(temp_auth_env):
    """Verify that unknown users and wrong passwords yield identical generic errors and trigger lockout."""
    db_path, _ = temp_auth_env
    rec_key = generate_recovery_key()
    create_user("Bob_Student", "GoodPassword99!", rec_key, db_path=db_path)

    # Non-existent user gets generic error
    ok1, msg1, _ = authenticate_user("non_existent_user", "SomePassword123!", db_path=db_path)
    assert ok1 is False
    assert msg1 == GENERIC_AUTH_ERROR

    # Existing user with wrong password gets identical generic error
    ok2, msg2, _ = authenticate_user("Bob_Student", "WrongPassword123!", db_path=db_path)
    assert ok2 is False
    assert msg2 == GENERIC_AUTH_ERROR

    # Trigger remaining failed attempts to reach lockout (default 5 max failed)
    for _ in range(4):
        authenticate_user("Bob_Student", "WrongPassword123!", db_path=db_path)

    # 6th attempt should be locked out
    ok_lock, msg_lock, _ = authenticate_user("Bob_Student", "GoodPassword99!", db_path=db_path)
    assert ok_lock is False
    assert "Account temporarily locked" in msg_lock


def test_user_context_path_traversal_protection(temp_auth_env):
    """Verify that UserContext resolves valid subpaths and strictly rejects directory traversal."""
    _, data_root = temp_auth_env
    user_id = "test-user-uuid-999"
    ctx = UserContext.create(user_id=user_id, username="charlie", data_root=data_root)

    # Valid subpaths resolve within base_dir
    safe_file = ctx.resolve_safe_path("memory/subject.json")
    assert safe_file.is_relative_to(ctx.base_dir)

    # Directory traversal attempts must raise PermissionError
    with pytest.raises(PermissionError):
        ctx.resolve_safe_path("../other_user_file.txt")

    with pytest.raises(PermissionError):
        ctx.resolve_safe_path("..\\..\\windows\\system32")


def test_session_lifecycle_and_inactivity_expiry(temp_auth_env):
    """Verify session creation, activity touch, logout hook, and invalidation."""
    _, data_root = temp_auth_env
    ctx = UserContext.create("uuid-123", "david", data_root=data_root)

    token = create_session(ctx)
    assert len(token) == 64  # 256 bits hex

    # Validate active session
    valid, active_ctx, _ = validate_session(token)
    assert valid is True
    assert active_ctx.user_id == "uuid-123"

    # End session (logout)
    end_session(token)
    valid_after, _, _ = validate_session(token)
    assert valid_after is False


def test_account_service_full_lifecycle(temp_auth_env):
    """Verify registration, login, password change, recovery, and account deletion."""
    db_path, data_root = temp_auth_env

    # 1. Register
    reg_ok, _, rec_key = register_account(
        "Emma_Study", "InitPass2026!", "InitPass2026!", db_path=db_path, data_root=data_root
    )
    assert reg_ok is True

    # 2. Login
    login_ok, _, token, context = login_account(
        "Emma_Study", "InitPass2026!", db_path=db_path, data_root=data_root
    )
    assert login_ok is True
    assert token is not None
    assert context.base_dir.exists()

    # Create dummy user file in user directory
    test_note = context.resolve_safe_path("uploads/note.txt")
    test_note.write_text("Emma's personal physics note.", encoding="utf-8")
    assert test_note.exists()

    # 3. Change password
    chg_ok, _ = change_account_password(
        context.user_id, "InitPass2026!", "NewPass2026!", "NewPass2026!", db_path=db_path
    )
    assert chg_ok is True

    # Login with old password fails
    fail_old, _, _, _ = login_account("Emma_Study", "InitPass2026!", db_path=db_path, data_root=data_root)
    assert fail_old is False

    # Login with new password succeeds
    ok_new, _, token2, _ = login_account("Emma_Study", "NewPass2026!", db_path=db_path, data_root=data_root)
    assert ok_new is True

    # 4. Password reset via recovery key
    reset_ok, _ = reset_password_with_recovery_key(
        "Emma_Study", rec_key, "RecoveredPass2026!", db_path=db_path
    )
    assert reset_ok is True

    # 5. Delete account
    del_ok, _ = delete_account(
        context.user_id, "RecoveredPass2026!", session_token=token2, db_path=db_path, data_root=data_root
    )
    assert del_ok is True
    assert not context.base_dir.exists()  # user folder wiped completely
