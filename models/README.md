# Brain Models (`models/`)

This directory encapsulates all large language model (LLM) and embedding integrations.

## Architecture Rule
As strictly enforced by the system architecture, no file outside of `models/brain.py` may mention or import specific LLM providers. All components access the language model solely through `models.brain.chat(messages, tools=None, options=None)`.

## Files
- `brain.py`: The single gateway interface for LLM calls supporting native and portable tool-calling, fallback execution, and provider translation.
- `mock_brain.py`: Offline scripted brain implementation used for unit tests, verifying prompt isolation, and test suites.
- `hardware.py`: Hardware preflight diagnostics detecting RAM, GPU type (dedicated AMD RX 6600 vs shared-memory Ryzen AI / Radeon 860M), Ollama status, and tokens/second.

## What to Edit
- To modify how provider calls are dispatched or how errors are handled, edit `brain.py`.
- To adjust mock testing behavior, edit `mock_brain.py`.
- To update hardware detection heuristics, edit `hardware.py`.
