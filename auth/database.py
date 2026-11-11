"""SQLite authentication database for user credentials and throttling."""

import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from auth.hasher import (
    check_password_strength,
    hash_password,
    hash_recovery_key,
    validate_username,
    verify_password,
    verify_recovery_key,
)
from config.loader import load_settings_config

GENERIC_AUTH_ERROR = "Invalid username or password."
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
AUTH_DB_PATH = DATA_DIR / "auth.db"


def get_db_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Open or create a connection to the SQLite authentication database."""
    target_path = db_path or AUTH_DB_PATH
    target_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_auth_db(db_path: Optional[Path] = None) -> None:
    """Initialize the schema of the isolated auth.db database."""
    conn = get_db_connection(db_path)
    with conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                display_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                recovery_key_hash TEXT NOT NULL,
                created_at REAL NOT NULL,
                failed_attempts INTEGER DEFAULT 0,
                last_failed_at REAL DEFAULT 0,
                lockout_until REAL DEFAULT 0
            )
            """
        )
    conn.close()


def create_user(
    username: str,
    password: str,
    recovery_key: str,
    db_path: Optional[Path] = None,
) -> Tuple[bool, str, Optional[str]]:
    """Register a new user account, returning success status, message, and user UUID."""
    init_auth_db(db_path)

    # Validate username
    valid_name, name_msg = validate_username(username)
    if not valid_name:
        return False, name_msg, None

    # Validate password
    valid_pw, pw_msg = check_password_strength(password)
    if not valid_pw:
        return False, pw_msg, None

    user_uuid = str(uuid.uuid4())
    norm_username = username.strip().lower()
    pw_hash = hash_password(password)
    rec_hash = hash_recovery_key(recovery_key)
    now = time.time()

    conn = get_db_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO users (id, username, display_name, password_hash, recovery_key_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_uuid, norm_username, username.strip(), pw_hash, rec_hash, now),
            )
        return True, "User registered successfully.", user_uuid
    except sqlite3.IntegrityError:
        return False, f"Username '{username}' is already taken.", None
    finally:
        conn.close()


def authenticate_user(
    username: str,
    password: str,
    db_path: Optional[Path] = None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Authenticate user with constant-time verification and lockout throttling."""
    init_auth_db(db_path)
    norm_username = username.strip().lower()
    now = time.time()

    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username = ?", (norm_username,))
        row = cursor.fetchone()

        if not row:
            # Fake hash check to prevent timing analysis on username existence
            hash_password("dummy-password-for-timing")
            return False, GENERIC_AUTH_ERROR, None

        # Check if user is locked out
        lockout_until = row["lockout_until"]
        if lockout_until and now < lockout_until:
            remaining = int(lockout_until - now)
            return False, f"Account temporarily locked due to failed attempts. Try again in {remaining} seconds.", None

        stored_hash = row["password_hash"]
        is_valid, needs_rehash = verify_password(stored_hash, password)

        if not is_valid:
            # Increment failed attempts and apply throttling
            settings = load_settings_config().get("auth", {})
            max_failed = settings.get("max_failed_logins", 5)
            lockout_duration = settings.get("lockout_seconds", 300)

            new_failed = row["failed_attempts"] + 1
            new_lockout = 0.0
            if new_failed >= max_failed:
                new_lockout = now + lockout_duration

            with conn:
                conn.execute(
                    "UPDATE users SET failed_attempts = ?, last_failed_at = ?, lockout_until = ? WHERE id = ?",
                    (new_failed, now, new_lockout, row["id"]),
                )
            return False, GENERIC_AUTH_ERROR, None

        # Reset failed attempts on successful login and upgrade hash if needed
        with conn:
            if needs_rehash:
                new_hash = hash_password(password)
                conn.execute(
                    "UPDATE users SET failed_attempts = 0, lockout_until = 0, password_hash = ? WHERE id = ?",
                    (new_hash, row["id"]),
                )
            else:
                conn.execute(
                    "UPDATE users SET failed_attempts = 0, lockout_until = 0 WHERE id = ?",
                    (row["id"],),
                )

        user_info = {
            "id": row["id"],
            "username": row["username"],
            "display_name": row["display_name"],
            "created_at": row["created_at"],
        }
        return True, "Login successful.", user_info
    finally:
        conn.close()


def change_password(
    user_id: str,
    current_password: str,
    new_password: str,
    db_path: Optional[Path] = None,
) -> Tuple[bool, str]:
    """Update a user's password after verifying their current password."""
    init_auth_db(db_path)
    valid_pw, pw_msg = check_password_strength(new_password)
    if not valid_pw:
        return False, pw_msg

    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        if not row:
            return False, "User not found."

        is_valid, _ = verify_password(row["password_hash"], current_password)
        if not is_valid:
            return False, "Current password incorrect."

        new_hash = hash_password(new_password)
        with conn:
            conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, user_id))
        return True, "Password changed successfully."
    finally:
        conn.close()


def reset_password_with_recovery_key(
    username: str,
    recovery_key: str,
    new_password: str,
    db_path: Optional[Path] = None,
) -> Tuple[bool, str]:
    """Reset a user's password using their one-time recovery key."""
    init_auth_db(db_path)
    valid_pw, pw_msg = check_password_strength(new_password)
    if not valid_pw:
        return False, pw_msg

    norm_username = username.strip().lower()
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, recovery_key_hash FROM users WHERE username = ?", (norm_username,))
        row = cursor.fetchone()
        if not row:
            return False, "Account or recovery key not recognized."

        if not verify_recovery_key(row["recovery_key_hash"], recovery_key):
            return False, "Account or recovery key not recognized."

        new_hash = hash_password(new_password)
        with conn:
            conn.execute(
                "UPDATE users SET password_hash = ?, failed_attempts = 0, lockout_until = 0 WHERE id = ?",
                (new_hash, row["id"]),
            )
        return True, "Password reset successfully."
    finally:
        conn.close()


def delete_user_account(
    user_id: str,
    password: str,
    db_path: Optional[Path] = None,
) -> Tuple[bool, str]:
    """Delete a user account from auth.db after verifying the password."""
    init_auth_db(db_path)
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        if not row:
            return False, "User not found."

        is_valid, _ = verify_password(row["password_hash"], password)
        if not is_valid:
            return False, "Incorrect password. Account deletion aborted."

        with conn:
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        return True, "User account deleted."
    finally:
        conn.close()
