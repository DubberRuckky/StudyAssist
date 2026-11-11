"""Configuration loader for StudyAssist providers and system settings."""

import json
from pathlib import Path
from typing import Any, Dict


CONFIG_DIR = Path(__file__).resolve().parent
PROVIDERS_PATH = CONFIG_DIR / "providers.json"
SETTINGS_PATH = CONFIG_DIR / "settings.json"


def load_providers_config() -> Dict[str, Any]:
    """Load the LLM providers profile configuration from providers.json."""
    if not PROVIDERS_PATH.exists():
        raise FileNotFoundError(f"Configuration file not found: {PROVIDERS_PATH}")
    with open(PROVIDERS_PATH, "r", encoding="utf-8") as file_handle:
        return json.load(file_handle)


def save_providers_config(config_data: Dict[str, Any]) -> None:
    """Save the LLM providers profile configuration to providers.json."""
    with open(PROVIDERS_PATH, "w", encoding="utf-8") as file_handle:
        json.dump(config_data, file_handle, indent=2)


def load_settings_config() -> Dict[str, Any]:
    """Load general system settings from settings.json."""
    if not SETTINGS_PATH.exists():
        raise FileNotFoundError(f"Settings file not found: {SETTINGS_PATH}")
    with open(SETTINGS_PATH, "r", encoding="utf-8") as file_handle:
        return json.load(file_handle)


def save_settings_config(settings_data: Dict[str, Any]) -> None:
    """Save general system settings to settings.json."""
    with open(SETTINGS_PATH, "w", encoding="utf-8") as file_handle:
        json.dump(settings_data, file_handle, indent=2)


def get_active_profile() -> Dict[str, Any]:
    """Retrieve the currently active brain profile configuration."""
    providers = load_providers_config()
    active_name = providers.get("active_profile", "local_ollama")
    profile = providers.get("profiles", {}).get(active_name)
    if not profile:
        raise ValueError(f"Active brain profile '{active_name}' does not exist in providers.json")
    return {"name": active_name, **profile}
