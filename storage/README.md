# Storage Layer (`storage/`)

This directory implements the isolated per-user data layer for StudyAssist.

## Architecture Rule
Every storage function strictly requires a `UserContext` and verifies that all file operations resolve safely within `data/users/<user_id>/` to prevent any directory traversal.

## Files
- `db.py`: SQLite database manager for revision plans, quiz progress, and audit action logs.
- `vector_store.py`: ChromaDB manager for storing and retrieving document embeddings per user.
- `memory.py`: Per-subject JSON memory file manager tracking topic hierarchies, prerequisites, and learning order.
- `crypto.py`: Optional AES-256-GCM encryption at rest for raw uploaded documents and JSON memory files.

## What to Edit
- To alter database schema for quizzes or plans, edit `storage/db.py`.
- To modify vector indexing or similarity search parameters, edit `storage/vector_store.py`.
