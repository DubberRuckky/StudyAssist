# Test Suite (`tests/`)

This directory contains automated unit and integration tests using `pytest`.

## Offline Guarantee
All tests run completely offline without requiring an active Ollama instance, external cloud API keys, or network connections, thanks to `MockBrain`.

## Test Structure
- `test_auth_isolation.py`: Verifies Argon2id password hashing, constant-time verification, lockout, session tokens, and strict user isolation (preventing User A from reading User B's files).
- `test_storage.py`: Tests SQLite progress tracking, JSON memory files, path traversal rejection, and optional AES-256-GCM encryption.
- `test_brain.py`: Tests provider switching, fallback chains, native vs portable tool calling, JSON repair, and daily call limits.
- `test_hardware.py`: Tests hardware preflight diagnostics with synthetic CPU/RAM and GPU telemetry.
- `test_tools.py`: Tests document ingestion, topological topic ordering, quiz generation validation/retry, calendar exports, and progress metrics.
- `test_jury.py`: Tests 6-agent jury execution, role-label stripping for blind reviews, and weighted consensus.
- `test_agent.py`: Tests the full Goal -> Plan -> Act -> Approve -> Log cycle and human approval gate.
- `test_docs.py`: Validates that `README.md` documents all six tool names, all config files, Argon2id, recovery key, and the no-sync single-computer design.
- `test_smoke.py`: End-to-end integration smoke test running the web app logic with `MockBrain`.

## How to Run Tests
```bash
pytest -v
```
