# Changelog

All notable changes to the StudyAssist project will be documented in this file.

## [Milestone 11] - Colab Server Notebook, Full Documentation Pass, and Automated Docs & Smoke Tests
- Created `colab/brain_server.ipynb` and `colab/README.md` implementing an authenticated reverse proxy server for Ollama with Qwen 2.5 7B, complete with Google Colab Terms of Service warnings, bearer-token security, and Cloudflare tunnel instructions.
- Validated and audited full `README.md` ensuring all 14 mandatory sections, 6 agent tools, Argon2id security, recovery key recovery, local storage architecture, Vulkan setup (`OLLAMA_VULKAN=1`), and single-computer no-sync limitation are thoroughly documented.
- Implemented `tests/test_docs.py` automating documentation integrity checks across `README.md` and all subfolder-level README files.
- Implemented `tests/test_smoke.py` executing an end-to-end smoke verification covering user registration, file ingestion, ChromaDB vector querying, quiz generation, automated score grading, spaced-repetition scheduling through the approval gate, 6-agent jury deliberation, and SQLite action audit logging.

## [Milestone 10] - Brain Resilience, Daily Call Caps, Connection Diagnostics, and Storage Encryption
- Implemented daily LLM call tracking in user SQLite database (`daily_call_usage` table) with strict cap enforcement (`daily_call_cap`) to prevent runaway costs or compute.
- Enhanced `models/brain.py` with exponential backoff retries for Ollama and LiteLLM network/5xx server errors.
- Added comprehensive failure recovery in `models/brain.py` with clear, user-safe guidance preserving study databases and files when all candidate brain profiles fail.
- Implemented `test_brain_connection()` checking live reachability, installed model readiness, and keyring credentials.
- Implemented `estimate_jury_cost()` computing token and dollar estimates before launching 6-agent deliberative jury mode on paid/cloud providers.
- Implemented `storage/crypto.py` providing optional AES-256-GCM encryption at rest for uploads and subject memory JSON files:
  - Envelope encryption deriving keys from Argon2id via user password or emergency recovery key.
  - Transparent save and load encryption in `storage/memory.py`.
  - Batch encryption and decryption routines for user files.
- Added comprehensive unit tests in `tests/test_milestone10_resilience_crypto.py` covering daily quota enforcement, fallback chains, safe error messaging, hardware heuristics, connection testing, cost estimates, envelope vault unwrapping, and encrypted storage round-trips.

## [Milestone 9] - Gradio Web Interface and 127.0.0.1 Localhost Security
- Implemented `ui/dashboard.py` featuring modern Gradio Blocks interface:
  - Auth container supporting Registration (with one-time recovery key dialog), Login, and Account Recovery.
  - Multi-tab Dashboard: Chat with Assistant (interactive prompt, quick vs jury debate mode, streaming responses), Upload & Subjects (file upload, format tags, learning order visualization, and local-only subject privacy toggles), Progress & Quizzes (interactive quiz taking, automatic grading, and weakest topics list), Approvals (pending human confirmation queue for revision plans and actions), Brain & Settings (active profile switch, fallback order, hardware preflight check, and daily limits), and Action Log (full audit log of all agent tool actions).
- Implemented `app.py` importing all tool definitions and launching the web server bound strictly to `127.0.0.1:7860` with `share=False` enforced.
- Adapted to Gradio 6.x modern APIs, removing deprecated `css` and `bubble_full_width` parameters.
- Added unit tests in `tests/test_milestone9_ui.py` validating Blocks creation, strict 127.0.0.1 network safety binding, and complete tool registration on startup.

## [Milestone 8] - 6-Agent Deliberative Jury Debate and Quick Mode
- Implemented `agent/jury.py` orchestrating multi-agent debates with specialized roles: `explainer`, `rigorous_expert`, `skeptic`, `exam_coach`, `example_builder`, and `fact_checker`.
- Implemented Round 1 independent answers grounded in the same retrieved ChromaDB note passages.
- Implemented Round 2 blind peer review with role-label stripping (`Candidate Answer A..F`) to eliminate author bias.
- Implemented Chief Judicial Synthesizer integrating answers and critiques with configurable role influence weights and source citations.
- Implemented `tools/run_jury.py` supporting both Quick Mode (single agent, default on slow machines) and full Jury Mode.
- Added comprehensive unit tests in `tests/test_milestone8_jury.py` validating quick mode, blind label stripping, 6-agent debate rounds, and dispatcher tool execution.

## [Milestone 7] - Quiz Generation, Progress Tracking, and Revision Scheduling
- Implemented `tools/generate_quiz.py` generating grounded multiple-choice questions from retrieved notes with schema validation, one retry, and automatic grading that records evaluation scores in SQLite.
- Implemented `tools/track_progress.py` logging quiz points and returning weakest study topics ranked by mastery percentage for targeted revision.
- Implemented `tools/schedule_revision.py` computing spaced-repetition study allocations leading up to a target exam date, gated by human approval (`requires_confirmation`), and exporting standard `.ics` iCalendar files with VEVENT intervals.
- Resolved Python 3.13 deprecation warnings (modernizing to `pymupdf` and `datetime.now(timezone.utc)`).
- Added comprehensive unit tests in `tests/test_milestone7_quiz_progress_schedule.py` testing question generation, answer grading, weak topic rankings, and approval gate calendar exports.

## [Milestone 6] - File Ingestion, OCR, Memory Files, and Search Notes
- Implemented `tools/ingest_material.py` parsing PDFs (PyMuPDF), Word (.docx), presentations (.pptx), spreadsheets (.xlsx), plain text/markdown, and images with OCR (pytesseract).
- Added automatic OCR trigger for scanned PDF pages with minimal embedded text (<30 chars) and robust fallback when Tesseract binary is absent.
- Preserved exact page and slide numbers on all chunks and integrated deterministic topological topic sequencing in code.
- Implemented `tools/search_notes.py` querying ChromaDB and returning formatted passages with file, page, and topic citations.
- Added comprehensive unit tests in `tests/test_milestone6_ingest_search.py` verifying all supported file formats, error reporting on unsupported types, and manual topic order overrides.

## [Milestone 5] - Agent Loop, Human Approval Gate, and Action Log
- Implemented `agent/dispatcher.py` providing tool registry, human-in-the-loop confirmation gate (`requires_confirmation`), graceful exception handling as textual error output, and automatic audit logging.
- Implemented `agent/orchestrator.py` executing the Goal -> Plan -> Act -> Approve -> Log loop with iteration caps, execution timeouts, observation feedback, and structured completion reporting.
- Added comprehensive unit tests in `tests/test_milestone5_agent.py` testing error suppression, approval/rejection handling, MockBrain iteration steps, and cap enforcement.

## [Milestone 4] - Brain Gateway, Universal Tool Calling, and Hardware Preflight
- Implemented `models/brain.py` exposing unified `chat(messages, tools, options, user_context)` with single-thread brain queue lock, per-subject local-only enforcement, automatic fallback chains, and one-time remote provider notices.
- Implemented `models/tool_protocol.py` for universal tool calling in portable JSON mode (`{"action": "...", "args": {...}}`), including robust markdown fence stripping, trailing comma repair, schema validation with Pydantic, and corrective retry prompts.
- Implemented `models/hardware.py` running preflight checks for dedicated GPU desktops (AMD RX 6600) vs shared-memory laptops (Ryzen AI / Radeon 860M), calculating tokens/second benchmarks, and returning tailored Vulkan advice (`OLLAMA_VULKAN=1`).
- Added comprehensive unit tests in `tests/test_milestone4_brain.py` testing JSON repair, fallback transitions, local-only enforcement, and hardware verdict heuristics.

## [Milestone 3] - Isolated Storage Layer and Cross-User Isolation
- Implemented `storage/db.py` managing user-isolated SQLite databases (`data/users/<user_id>/study.db`) for quiz progress, weak topic aggregation, revision plans, subject toggles, and audit action logs.
- Implemented `storage/memory.py` managing per-subject JSON memory files and deterministic topological sorting of prerequisites into a learning sequence in code.
- Implemented `storage/vector_store.py` managing isolated per-user ChromaDB collections and chunk querying with page/source citations and offline deterministic embeddings fallback.
- Added comprehensive isolation tests in `tests/test_milestone3_storage.py` proving that User A cannot see, read, or query User B's progress, weak topics, vector notes, memory files, or action logs.

## [Milestone 2] - Authentication, Hashing, Sessions, and UserContext
- Implemented `auth/hasher.py` with Argon2id password hashing, unique random salt generation, password strength rules, and 128-bit `STUDY-...` recovery keys.
- Implemented `auth/database.py` managing `data/auth.db` with constant-time verification, exponential backoff, account lockout after 5 failed attempts, generic error messages, and recovery key resets.
- Implemented `auth/context.py` defining immutable `UserContext` with path traversal protections (`resolve_safe_path`).
- Implemented `auth/session.py` with 256-bit in-memory session tokens, idle timeout tracking, and logout cleanup hooks.
- Implemented `auth/service.py` exposing unified high-level account lifecycle methods (registration, login, logout, password change, account deletion).
- Added comprehensive unit tests in `tests/test_milestone2_auth.py` verifying hashing uniqueness, validation, lockout, traversal rejection, and full lifecycle.

## [Milestone 1] - Project Scaffolding & Core Architecture
- Created project directory structure (`agent/`, `auth/`, `config/`, `models/`, `storage/`, `tools/`, `ui/`, `tests/`).
- Initialized `requirements.txt` with Python 3.13 target dependencies.
- Configured `config/providers.json` with profiles for `local_ollama` (Qwen 2.5 7B), `local_fallback` (Qwen 2.5 3B), `colab_ollama` (tunnel), `remote_cloud` (LiteLLM), and `mock`.
- Configured `config/settings.json` with CPU offloading for embeddings (`nomic-embed-text`), hardware memory keep-alive, Argon2id security costs, spaced repetition settings, and jury role weights.
- Implemented `config/loader.py` for reading and saving JSON configurations.
- Implemented `auth/keyring_service.py` for isolating user API secrets per user ID in the OS keyring.
- Implemented `models/mock_brain.py` with offline scripted replies and prompt inspection capabilities for tests.
- Added comprehensive documentation skeletons and folder-level README files.
