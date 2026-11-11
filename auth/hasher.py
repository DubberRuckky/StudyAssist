"""Cryptographic password hashing and verification using Argon2id."""

import re
import secrets
from typing import Optional, Tuple
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError

from config.loader import load_settings_config

# A concise list of the most common insecure passwords
COMMON_PASSWORDS = {
    "password", "password123", "1234567890", "123456789", "12345678", "qwertyuiop",
    "admin1234", "letmein123", "welcome123", "studyassist", "changeme123", "iloveyou123"
}


def get_hasher() -> PasswordHasher:
    """Instantiate Argon2id hasher using parameters from settings.json."""
    try:
        settings = load_settings_config().get("auth", {})
        time_cost = settings.get("argon2_time_cost", 3)
        memory_cost = settings.get("argon2_memory_cost_kib", 65536)
        parallelism = settings.get("argon2_parallelism", 4)
    except Exception:
        time_cost = 3
        memory_cost = 65536
        parallelism = 4

    return PasswordHasher(
        time_cost=time_cost,
        memory_cost=memory_cost,
        parallelism=parallelism,
        hash_len=32,
        salt_len=16
    )


def validate_username(username: str) -> Tuple[bool, str]:
    """Validate username according to length and character rules."""
    if not username:
        return False, "Username cannot be empty."
    clean = username.strip()
    if len(clean) < 3 or len(clean) > 32:
        return False, "Username must be between 3 and 32 characters."
    if not re.match(r"^[A-Za-z0-9_-]+$", clean):
        return False, "Username may only contain letters, digits, underscores, and hyphens."
    return True, ""


def check_password_strength(password: str) -> Tuple[bool, str]:
    """Validate password strength and return plain-language guidance."""
    if not password or len(password) < 10:
        return False, "Password must be at least 10 characters long."
    if password.lower() in COMMON_PASSWORDS:
        return False, "This password is too common. Please pick a more unique passphrase."

    has_upper = any(c.isupper() for c in password)
    has_lower = any(c.islower() for c in password)
    has_digit = any(c.isdigit() for c in password)
    has_special = any(not c.isalnum() for c in password)

    score = sum([has_upper, has_lower, has_digit, has_special])
    if score < 2:
        return False, "Password should mix letters, numbers, or symbols for better security."

    return True, "Strong password."


def hash_password(password: str) -> str:
    """Hash a plaintext password using Argon2id with unique random salt."""
    hasher = get_hasher()
    return hasher.hash(password)


def verify_password(stored_hash: str, candidate_password: str) -> Tuple[bool, bool]:
    """Verify password in constant time and indicate if hash needs rehashing."""
    hasher = get_hasher()
    try:
        needs_rehash = hasher.check_needs_rehash(stored_hash)
        hasher.verify(stored_hash, candidate_password)
        return True, needs_rehash
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False, False


def generate_recovery_key() -> str:
    """Generate a high-entropy 128-bit one-time recovery key formatted in readable blocks."""
    raw_hex = secrets.token_hex(16).upper()
    blocks = [raw_hex[i:i + 4] for i in range(0, len(raw_hex), 4)]
    return f"STUDY-{'-'.join(blocks)}"


def hash_recovery_key(recovery_key: str) -> str:
    """Hash a recovery key with Argon2id for secure storage in auth.db."""
    clean_key = recovery_key.strip().upper()
    return hash_password(clean_key)


def verify_recovery_key(stored_hash: str, candidate_key: str) -> bool:
    """Verify a recovery key against stored Argon2id hash."""
    clean_key = candidate_key.strip().upper()
    valid, _ = verify_password(stored_hash, clean_key)
    return valid
