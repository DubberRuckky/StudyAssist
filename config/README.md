# Configuration (`config/`)

This directory holds all JSON configuration files and python configuration helpers for StudyAssist.

## Files
- `providers.json`: Defines brain profiles (local Ollama, fallback models, Colab tunnel, and cloud LiteLLM endpoints). No secrets or API keys are stored here.
- `settings.json`: System settings including embedding settings (CPU offloading), hardware parameters, authentication cost metrics, and jury weights.
- `loader.py`: Python module providing safe reading and writing functions for all configuration files.

## What to Edit
- To change the active LLM or adjust local Ollama URLs, edit `providers.json`.
- To adjust spaced repetition, daily token limits, or Argon2 password hashing costs, edit `settings.json`.
