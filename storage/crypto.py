"""Optional encryption at rest for user uploaded files and subject memory files using AES-256-GCM.

Derives encryption keys using Argon2id from the student's password or emergency recovery key.
Note: Vector store embeddings (ChromaDB) and local database indexes (SQLite) remain unencrypted
for query indexing speed.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import argon2.low_level
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from auth.context import UserContext
from config.loader import load_settings_config

MAGIC_HEADER = b"STUDY_ENC\x01"
ASSOCIATED_DATA = b"StudyAssistEncryptedFile"


def derive_key_from_password(password: str, salt: bytes) -> bytes:
    """Derive a 256-bit (32-byte) AES key from a user password using Argon2id."""
    settings = load_settings_config()
    auth_cfg = settings.get("auth", {})
    time_cost = auth_cfg.get("argon2_time_cost", 2)
    memory_cost = auth_cfg.get("argon2_memory_cost", 65536)
    parallelism = auth_cfg.get("argon2_parallelism", 1)

    return argon2.low_level.hash_secret_raw(
        secret=password.encode("utf-8"),
        salt=salt,
        time_cost=time_cost,
        memory_cost=memory_cost,
        parallelism=parallelism,
        hash_len=32,
        type=argon2.low_level.Type.ID,
    )


def derive_key_from_recovery_key(recovery_key: str, salt: bytes) -> bytes:
    """Derive a 256-bit AES key from a student emergency recovery key."""
    normalized = recovery_key.strip().upper().replace(" ", "")
    # Use standard Argon2id derivation
    return argon2.low_level.hash_secret_raw(
        secret=normalized.encode("utf-8"),
        salt=salt,
        time_cost=2,
        memory_cost=65536,
        parallelism=1,
        hash_len=32,
        type=argon2.low_level.Type.ID,
    )


def encrypt_bytes(data: bytes, key: bytes) -> bytes:
    """Encrypt raw bytes using AES-256-GCM with a random 96-bit nonce and magic header."""
    if is_encrypted_bytes(data):
        return data  # Avoid double-encryption

    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ciphertext_and_tag = aesgcm.encrypt(nonce, data, ASSOCIATED_DATA)
    return MAGIC_HEADER + nonce + ciphertext_and_tag


def decrypt_bytes(payload: bytes, key: bytes) -> bytes:
    """Decrypt payload using AES-256-GCM. Returns raw bytes unchanged if not encrypted."""
    if not is_encrypted_bytes(payload):
        return payload

    nonce = payload[len(MAGIC_HEADER) : len(MAGIC_HEADER) + 12]
    ciphertext_and_tag = payload[len(MAGIC_HEADER) + 12 :]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext_and_tag, ASSOCIATED_DATA)


def is_encrypted_bytes(data: bytes) -> bool:
    """Check if byte data starts with the StudyAssist encryption magic header."""
    return data.startswith(MAGIC_HEADER)


def encrypt_file(file_path: Path, key: bytes) -> bool:
    """Encrypt a single file in-place if not already encrypted."""
    if not file_path.exists():
        return False
    data = file_path.read_bytes()
    if is_encrypted_bytes(data):
        return False
    encrypted = encrypt_bytes(data, key)
    file_path.write_bytes(encrypted)
    return True


def decrypt_file(file_path: Path, key: bytes) -> bytes:
    """Read and decrypt a file, returning plaintext bytes."""
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    data = file_path.read_bytes()
    return decrypt_bytes(data, key)


def setup_encryption_vault(
    context: UserContext,
    password: str,
    recovery_key: str,
) -> bytes:
    """Initialize master key vault wrapped by both password and recovery key."""
    master_key = os.urandom(32)
    salt = os.urandom(16)

    pwd_key = derive_key_from_password(password, salt)
    rec_key = derive_key_from_recovery_key(recovery_key, salt)

    nonce_pwd = os.urandom(12)
    wrapped_pwd = AESGCM(pwd_key).encrypt(nonce_pwd, master_key, b"pwd_wrap")

    nonce_rec = os.urandom(12)
    wrapped_rec = AESGCM(rec_key).encrypt(nonce_rec, master_key, b"rec_wrap")

    vault_path = context.resolve_safe_path("vault.json")
    vault_data = {
        "salt_hex": salt.hex(),
        "nonce_pwd_hex": nonce_pwd.hex(),
        "wrapped_pwd_hex": wrapped_pwd.hex(),
        "nonce_rec_hex": nonce_rec.hex(),
        "wrapped_rec_hex": wrapped_rec.hex(),
        "enabled": True,
    }
    vault_path.write_text(json.dumps(vault_data, indent=2), encoding="utf-8")
    return master_key


def unwrap_master_key_with_password(context: UserContext, password: str) -> Optional[bytes]:
    """Unwrap the user's master encryption key using their password."""
    vault_path = context.resolve_safe_path("vault.json")
    if not vault_path.exists():
        return None

    vault_data = json.loads(vault_path.read_text(encoding="utf-8"))
    salt = bytes.fromhex(vault_data["salt_hex"])
    nonce = bytes.fromhex(vault_data["nonce_pwd_hex"])
    wrapped = bytes.fromhex(vault_data["wrapped_pwd_hex"])

    pwd_key = derive_key_from_password(password, salt)
    try:
        return AESGCM(pwd_key).decrypt(nonce, wrapped, b"pwd_wrap")
    except Exception:
        return None


def unwrap_master_key_with_recovery_key(context: UserContext, recovery_key: str) -> Optional[bytes]:
    """Unwrap the user's master encryption key using their emergency recovery key."""
    vault_path = context.resolve_safe_path("vault.json")
    if not vault_path.exists():
        return None

    vault_data = json.loads(vault_path.read_text(encoding="utf-8"))
    salt = bytes.fromhex(vault_data["salt_hex"])
    nonce = bytes.fromhex(vault_data["nonce_rec_hex"])
    wrapped = bytes.fromhex(vault_data["wrapped_rec_hex"])

    rec_key = derive_key_from_recovery_key(recovery_key, salt)
    try:
        return AESGCM(rec_key).decrypt(nonce, wrapped, b"rec_wrap")
    except Exception:
        return None


def rewrap_vault_password(
    context: UserContext,
    master_key: bytes,
    new_password: str,
) -> None:
    """Update vault after password change while retaining recovery key unwrapping."""
    vault_path = context.resolve_safe_path("vault.json")
    if not vault_path.exists():
        return

    vault_data = json.loads(vault_path.read_text(encoding="utf-8"))
    salt = bytes.fromhex(vault_data["salt_hex"])

    pwd_key = derive_key_from_password(new_password, salt)
    nonce_pwd = os.urandom(12)
    wrapped_pwd = AESGCM(pwd_key).encrypt(nonce_pwd, master_key, b"pwd_wrap")

    vault_data["nonce_pwd_hex"] = nonce_pwd.hex()
    vault_data["wrapped_pwd_hex"] = wrapped_pwd.hex()

    vault_path.write_text(json.dumps(vault_data, indent=2), encoding="utf-8")


def encrypt_user_study_files(context: UserContext, master_key: bytes) -> Dict[str, int]:
    """Encrypt all files in user uploads and memory directories."""
    count = 0
    uploads_dir = context.resolve_safe_path("uploads")
    if uploads_dir.exists():
        for f in uploads_dir.rglob("*"):
            if f.is_file() and not is_encrypted_bytes(f.read_bytes()[:16]):
                if encrypt_file(f, master_key):
                    count += 1

    memory_dir = context.resolve_safe_path("memory")
    if memory_dir.exists():
        for f in memory_dir.rglob("*.json"):
            if f.is_file() and not is_encrypted_bytes(f.read_bytes()[:16]):
                if encrypt_file(f, master_key):
                    count += 1

    return {"encrypted_count": count}


def decrypt_user_study_files(context: UserContext, master_key: bytes) -> Dict[str, int]:
    """Decrypt all files in user uploads and memory directories."""
    count = 0
    uploads_dir = context.resolve_safe_path("uploads")
    if uploads_dir.exists():
        for f in uploads_dir.rglob("*"):
            if f.is_file() and is_encrypted_bytes(f.read_bytes()[:16]):
                dec = decrypt_file(f, master_key)
                f.write_bytes(dec)
                count += 1

    memory_dir = context.resolve_safe_path("memory")
    if memory_dir.exists():
        for f in memory_dir.rglob("*.json"):
            if f.is_file() and is_encrypted_bytes(f.read_bytes()[:16]):
                dec = decrypt_file(f, master_key)
                f.write_bytes(dec)
                count += 1

    return {"decrypted_count": count}
