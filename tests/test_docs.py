"""Documentation validation tests ensuring README.md and sub-READMEs remain accurate and complete."""

from pathlib import Path
import pytest


def test_readme_exists_and_contains_required_sections():
    """Verify that root README.md exists and contains all 14 mandatory sections."""
    readme_path = Path("README.md")
    assert readme_path.exists(), "README.md must exist in project root."
    content = readme_path.read_text(encoding="utf-8")

    expected_sections = [
        "1. What This Is",
        "2. Quick Start",
        "3. Choosing a Brain",
        "4. Using an AMD GPU on Windows & Target Machines",
        "5. Accounts, Login, and Isolation",
        "6. How It Works: Tools and the Jury",
        "7. Folder Map",
        "8. Configuration Guide",
        "9. How to Change Things",
        "10. Privacy & Security Notes",
        "11. Testing Guide",
        "12. Troubleshooting",
        "13. Glossary of Terms",
        "14. Assumptions, Known Limitations & Maintenance Checklist",
    ]

    for section in expected_sections:
        assert section in content, f"Missing section '{section}' in README.md"


def test_readme_mentions_ai_coding_agent():
    """Verify attribution that an AI coding agent assisted in development."""
    readme_path = Path("README.md")
    content = readme_path.read_text(encoding="utf-8")
    assert "AI coding agent" in content, "README must mention AI coding agent contribution."


def test_readme_mentions_all_six_tools():
    """Verify README mentions all 6 canonical agent tools."""
    readme_path = Path("README.md")
    content = readme_path.read_text(encoding="utf-8")

    canonical_tools = [
        "ingest_material",
        "search_notes",
        "run_jury",
        "generate_quiz",
        "schedule_revision",
        "track_progress",
    ]

    for tool in canonical_tools:
        assert tool in content, f"Tool '{tool}' must be documented in README.md"


def test_readme_mentions_config_files():
    """Verify config files are documented."""
    readme_path = Path("README.md")
    content = readme_path.read_text(encoding="utf-8")

    assert "config/providers.json" in content
    assert "config/settings.json" in content


def test_readme_mentions_security_and_known_limitations():
    """Verify security specifics (Argon2id, recovery key) and single-computer no-sync limitation."""
    readme_path = Path("README.md")
    content = readme_path.read_text(encoding="utf-8")

    assert "Argon2id" in content
    assert "recovery key" in content
    assert "No Sync" in content or "no sync" in content.lower()
    assert "127.0.0.1" in content


def test_all_subfolders_contain_readmes():
    """Verify that all core subdirectories contain folder-level README.md files."""
    core_folders = [
        "agent",
        "auth",
        "colab",
        "config",
        "models",
        "storage",
        "tools",
        "ui",
    ]

    for folder in core_folders:
        sub_readme = Path(folder) / "README.md"
        assert sub_readme.exists(), f"Subfolder '{folder}' is missing a README.md file."
        assert len(sub_readme.read_text(encoding="utf-8").strip()) > 50, f"README.md in '{folder}' is too short."
