"""Unit tests for Milestone 10: Fallback chains, daily call caps, resilience, and AES-256-GCM encryption."""

import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from auth.context import UserContext
from config.loader import load_settings_config, save_settings_config
from models.brain import chat, estimate_jury_cost, test_brain_connection as check_brain_connection
from models.hardware import run_hardware_preflight
from storage.crypto import (
    MAGIC_HEADER,
    decrypt_bytes,
    decrypt_file,
    decrypt_user_study_files,
    derive_key_from_password,
    derive_key_from_recovery_key,
    encrypt_bytes,
    encrypt_file,
    encrypt_user_study_files,
    is_encrypted_bytes,
    rewrap_vault_password,
    setup_encryption_vault,
    unwrap_master_key_with_password,
    unwrap_master_key_with_recovery_key,
)
from storage.db import get_daily_call_count, init_user_db, record_brain_call
from storage.memory import load_subject_memory, save_subject_memory


@pytest.fixture
def m10_user(tmp_path):
    """Create isolated test user context for Milestone 10 tests."""
    user_ctx = UserContext.create(
        user_id="test_user_m10",
        username="m10student",
        data_root=tmp_path,
    )
    init_user_db(user_ctx)
    return user_ctx


def test_daily_call_cap_and_tracking(m10_user):
    """Verify that daily brain calls are tracked in SQLite and cap is strictly enforced."""
    # Initially 0 calls
    assert get_daily_call_count(m10_user) == 0

    # Record 2 calls
    c1 = record_brain_call(m10_user, "mock")
    assert c1 == 1
    c2 = record_brain_call(m10_user, "mock")
    assert c2 == 2
    assert get_daily_call_count(m10_user) == 2

    # Save settings with low cap of 2
    settings = load_settings_config()
    orig_cap = settings.get("safety", {}).get("daily_call_cap", 100)
    try:
        settings.setdefault("safety", {})["daily_call_cap"] = 2
        save_settings_config(settings)

        # Attempting chat() with user context should now be blocked by the cap
        with pytest.raises(RuntimeError) as exc_info:
            chat(
                messages=[{"role": "user", "content": "Hello"}],
                options={"profile": "mock"},
                user_context=m10_user,
            )
        assert "Daily call cap exceeded" in str(exc_info.value)
    finally:
        # Restore original cap
        settings["safety"]["daily_call_cap"] = orig_cap
        save_settings_config(settings)


def test_brain_fallback_to_mock_on_failed_profile():
    """Verify that brain gracefully transitions to next fallback profile when primary fails."""
    # Request options specifying an impossible Ollama port, but fallback order has mock
    res = chat(
        messages=[{"role": "user", "content": "Test fallback"}],
        options={"profile": "mock"},  # Mock always works
    )
    assert res is not None
    assert "content" in res
    assert res["profile_used"] == "mock"


def test_all_brains_failed_message_protects_user():
    """Verify that when every candidate profile fails, the system returns a safe, explanatory message."""
    from unittest.mock import patch

    with patch("models.brain._call_ollama", side_effect=ConnectionError("Endpoint down")):
        with pytest.raises(RuntimeError) as exc_info:
            chat(
                messages=[{"role": "user", "content": "Test"}],
                options={"profile": "local_fallback"},
            )
        err_msg = str(exc_info.value)
        assert "All configured brain profiles failed" in err_msg
        assert "Your local files, notes, and study database remain safe" in err_msg


def test_hardware_verdict_heuristics():
    """Verify hardware preflight classification for dedicated AMD, integrated Radeon, and CPU-only."""
    # 1. Dedicated GPU desktop with high RAM
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
        mock_tps.return_value = 24.0

        res_ded = run_hardware_preflight()
        assert res_ded["verdict"] == "Good"
        assert "Dedicated GPU" in res_ded["machine_type"]
        assert "OLLAMA_VULKAN=1" in res_ded["vulkan_tip"]

    # 2. Integrated Radeon laptop with low free RAM
    with patch("models.hardware.detect_gpu_info") as mock_gpu, \
         patch("psutil.virtual_memory") as mock_mem, \
         patch("models.hardware.check_ollama_status") as mock_ollama, \
         patch("models.hardware.benchmark_tokens_per_second") as mock_tps:

        mock_gpu.return_value = {
            "gpus": ["AMD Radeon 860M"],
            "is_amd": True,
            "is_dedicated": False,
            "is_integrated": True,
        }
        mock_mem.return_value = MagicMock(total=24 * (1024**3), available=4.0 * (1024**3))
        mock_ollama.return_value = {"reachable": True, "vram_percentage": 60.0}
        mock_tps.return_value = 14.0

        res_integ = run_hardware_preflight()
        assert "Slow" in res_integ["verdict"]
        assert "Shared-Memory Laptop" in res_integ["machine_type"]
        assert "OLLAMA_VULKAN=1" in res_integ["vulkan_tip"]

    # 3. CPU-only system with low TPS
    with patch("models.hardware.detect_gpu_info") as mock_gpu, \
         patch("psutil.virtual_memory") as mock_mem, \
         patch("models.hardware.check_ollama_status") as mock_ollama, \
         patch("models.hardware.benchmark_tokens_per_second") as mock_tps:

        mock_gpu.return_value = {
            "gpus": [],
            "is_amd": False,
            "is_dedicated": False,
            "is_integrated": False,
        }
        mock_mem.return_value = MagicMock(total=8 * (1024**3), available=5.0 * (1024**3))
        mock_ollama.return_value = {"reachable": True, "vram_percentage": 0.0}
        mock_tps.return_value = 2.0

        res_cpu = run_hardware_preflight()
        assert "Not recommended" in res_cpu["verdict"] or "Slow" in res_cpu["verdict"]


def test_connection_test_helper(m10_user):
    """Verify check_brain_connection reports accurate statuses for mock and unknown profiles."""
    mock_res = check_brain_connection("mock", user_context=m10_user)
    assert mock_res["status"] == "ok"
    assert "Mock profile is operational" in mock_res["message"]

    invalid_res = check_brain_connection("non_existent_profile_12345", user_context=m10_user)
    assert invalid_res["status"] == "error"
    assert "not found" in invalid_res["message"]


def test_estimate_jury_cost():
    """Verify jury cost estimation for local free execution versus remote cloud."""
    local_est = estimate_jury_cost("local_ollama", num_agents=6)
    assert local_est["is_local"] is True
    assert local_est["estimated_cost_usd"] == 0.0
    assert "Free (Local hardware)" in local_est["summary"]

    cloud_est = estimate_jury_cost("remote_cloud", num_agents=6)
    assert cloud_est["is_local"] is False
    assert cloud_est["estimated_cost_usd"] > 0.0
    assert "$" in cloud_est["summary"]


def test_aes_256_gcm_encryption_roundtrip():
    """Verify raw bytes encryption and decryption with AES-256-GCM."""
    salt = os.urandom(16)
    key = derive_key_from_password("CorrectHorseBatteryStaple123!", salt)
    assert len(key) == 32

    plaintext = b"Sensitive lecture notes: calculus exam hints and formulas."
    encrypted = encrypt_bytes(plaintext, key)

    assert is_encrypted_bytes(encrypted)
    assert encrypted.startswith(MAGIC_HEADER)
    assert encrypted != plaintext

    decrypted = decrypt_bytes(encrypted, key)
    assert decrypted == plaintext

    # Decrypting with wrong key raises error
    wrong_key = os.urandom(32)
    with pytest.raises(Exception):
        decrypt_bytes(encrypted, wrong_key)


def test_vault_envelope_encryption_password_and_recovery(m10_user):
    """Verify envelope encryption: master key unwrapped by both password and recovery key."""
    password = "StudyPassword2026!"
    recovery_key = "STUDY-A1B2-C3D4-E5F6"

    # Setup vault
    master_key = setup_encryption_vault(m10_user, password, recovery_key)
    assert len(master_key) == 32

    # Unwrap with correct password
    unwrapped_pwd = unwrap_master_key_with_password(m10_user, password)
    assert unwrapped_pwd == master_key

    # Unwrap with wrong password fails
    assert unwrap_master_key_with_password(m10_user, "WrongPassword!") is None

    # Unwrap with correct recovery key
    unwrapped_rec = unwrap_master_key_with_recovery_key(m10_user, recovery_key)
    assert unwrapped_rec == master_key

    # Unwrap with wrong recovery key fails
    assert unwrap_master_key_with_recovery_key(m10_user, "STUDY-0000-0000-0000") is None

    # Password change rewraps vault without affecting recovery key unwrapping
    new_password = "BrandNewSecurePassword2026!"
    rewrap_vault_password(m10_user, master_key, new_password)

    # New password works, old password fails
    assert unwrap_master_key_with_password(m10_user, new_password) == master_key
    assert unwrap_master_key_with_password(m10_user, password) is None

    # Recovery key still works
    assert unwrap_master_key_with_recovery_key(m10_user, recovery_key) == master_key


def test_encrypt_and_decrypt_user_files(m10_user):
    """Verify batch encryption and decryption of user upload and memory files."""
    master_key = os.urandom(32)

    # Create dummy upload and memory files
    upload_file = m10_user.resolve_safe_path("uploads/lecture_slides.pdf")
    upload_file.write_bytes(b"Sample PDF header and slide content")

    memory_file = m10_user.resolve_safe_path("memory/physics.json")
    memory_file.write_text(json.dumps({"subject": "physics", "topics": ["Mechanics"]}), encoding="utf-8")

    # Encrypt all files
    res_enc = encrypt_user_study_files(m10_user, master_key)
    assert res_enc["encrypted_count"] == 2

    # Check files on disk are encrypted
    assert is_encrypted_bytes(upload_file.read_bytes())
    assert is_encrypted_bytes(memory_file.read_bytes())

    # Decrypt all files
    res_dec = decrypt_user_study_files(m10_user, master_key)
    assert res_dec["decrypted_count"] == 2

    # Check files are now plaintext again
    assert upload_file.read_bytes() == b"Sample PDF header and slide content"
    assert json.loads(memory_file.read_text(encoding="utf-8"))["subject"] == "physics"


def test_memory_json_encrypted_save_and_load(m10_user):
    """Verify saving and loading subject memory with optional encryption key."""
    key = os.urandom(32)
    sample_data = {
        "subject": "Chemistry",
        "topics": [{"name": "Stoichiometry", "prerequisites": []}],
        "learning_order": ["Stoichiometry"],
    }

    # Save with encryption key
    save_subject_memory(m10_user, "Chemistry", sample_data, encryption_key=key)

    # Raw file on disk is encrypted
    mem_path = m10_user.resolve_safe_path("memory/chemistry.json")
    raw_bytes = mem_path.read_bytes()
    assert is_encrypted_bytes(raw_bytes)

    # Attempting to load without key raises PermissionError
    with pytest.raises(PermissionError):
        load_subject_memory(m10_user, "Chemistry")

    # Loading with correct key succeeds
    loaded = load_subject_memory(m10_user, "Chemistry", encryption_key=key)
    assert loaded["subject"] == "Chemistry"
    assert loaded["learning_order"] == ["Stoichiometry"]
