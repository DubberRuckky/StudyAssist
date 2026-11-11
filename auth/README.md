# Authentication & Account Security (`auth/`)

This directory provides secure local user authentication, password hashing, session throttling, and isolated user contexts.

## Security Highlights
- Passwords are strictly hashed with **Argon2id** (`argon2-cffi`) using unique random salts and constant-time verification.
- User material and files are isolated under `data/users/<user_id>/` where `<user_id>` is a secure UUID.
- Secrets (such as API keys and Colab tokens) are stored in the OS keyring under per-user service identifiers (`StudyAssist_User_<user_id>`).
- Throttling and lockout prevent brute-force attacks on shared family computers.

## Files
- `database.py`: Manages `data/auth.db` containing user accounts, hashes, recovery key hashes, and login attempt counters.
- `hasher.py`: Implements Argon2id hashing, verification, and recovery key generation.
- `session.py`: Manages in-memory 256-bit session tokens, idle expiration, and per-user cache clearance.
- `keyring_service.py`: Interfaces with the operating system keyring for secure credential isolation.
- `context.py`: Defines `UserContext`, the single object passed to every storage, tool, and agent operation.

## What to Edit
- To modify password rules or lockout parameters, edit `config/settings.json` or `auth/hasher.py`.
- To update session lifetime, edit `auth/session.py`.
