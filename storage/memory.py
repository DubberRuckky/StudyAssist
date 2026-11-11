"""Per-subject JSON memory file manager and deterministic topic ordering."""

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from auth.context import UserContext


def _sanitize_subject_filename(subject: str) -> str:
    """Produce a safe filesystem filename from a subject string."""
    clean = re.sub(r"[^\w\-]", "_", subject.strip().lower())
    return clean or "default_subject"


def compute_learning_order(topics: List[Dict[str, Any]]) -> List[str]:
    """Deterministically order topics using topological sorting based on prerequisites."""
    # Build graph: topic -> prerequisites
    adj: Dict[str, List[str]] = {}
    in_degree: Dict[str, int] = {}
    all_topic_names = set()

    for item in topics:
        name = item.get("name", "").strip()
        if not name:
            continue
        all_topic_names.add(name)
        prereqs = [p.strip() for p in item.get("prerequisites", []) if p.strip()]
        adj[name] = prereqs
        if name not in in_degree:
            in_degree[name] = 0

    # Ensure all mentioned prerequisites exist in graph
    for name, prereqs in adj.items():
        for p in prereqs:
            if p not in in_degree:
                in_degree[p] = 0
                adj[p] = []
                all_topic_names.add(p)

    # Invert to prerequisite -> dependents for standard Kahn's algorithm
    dependents: Dict[str, List[str]] = {t: [] for t in all_topic_names}
    for t, prereqs in adj.items():
        in_degree[t] = len(prereqs)
        for p in prereqs:
            dependents[p].append(t)

    # Queue of nodes with zero unsatisfied prerequisites (alphabetically sorted for determinism)
    zero_in = sorted([t for t, deg in in_degree.items() if deg == 0])
    ordered_topics: List[str] = []

    while zero_in:
        current = zero_in.pop(0)
        ordered_topics.append(current)
        for dep in dependents.get(current, []):
            in_degree[dep] -= 1
            if in_degree[dep] == 0:
                zero_in.append(dep)
        zero_in.sort()

    # If any cycle prevented total ordering, append remaining topics deterministically
    if len(ordered_topics) < len(all_topic_names):
        remaining = sorted([t for t in all_topic_names if t not in ordered_topics])
        ordered_topics.extend(remaining)

    return ordered_topics


def get_memory_file_path(context: UserContext, subject: str) -> Path:
    """Return the resolved path to a subject's JSON memory file."""
    filename = f"{_sanitize_subject_filename(subject)}.json"
    return context.resolve_safe_path(f"memory/{filename}")


def load_subject_memory(
    context: UserContext,
    subject: str,
    encryption_key: Optional[bytes] = None,
) -> Dict[str, Any]:
    """Load the JSON memory file for a specific subject, decrypting if encrypted."""
    file_path = get_memory_file_path(context, subject)
    if not file_path.exists():
        now = time.time()
        return {
            "subject": subject.strip(),
            "created_at": now,
            "updated_at": now,
            "local_only": False,
            "files": [],
            "topics": [],
            "learning_order": [],
        }

    raw_bytes = file_path.read_bytes()
    if raw_bytes.startswith(b"STUDY_ENC\x01"):
        if not encryption_key:
            raise PermissionError(f"Subject memory file for '{subject}' is encrypted. Key required to read.")
        from storage.crypto import decrypt_bytes
        raw_bytes = decrypt_bytes(raw_bytes, encryption_key)

    return json.loads(raw_bytes.decode("utf-8"))


def save_subject_memory(
    context: UserContext,
    subject: str,
    memory_data: Dict[str, Any],
    encryption_key: Optional[bytes] = None,
) -> None:
    """Save or update the JSON memory file for a subject with updated timestamps and optional encryption."""
    file_path = get_memory_file_path(context, subject)
    memory_data["subject"] = subject.strip()
    memory_data["updated_at"] = time.time()
    if "created_at" not in memory_data:
        memory_data["created_at"] = memory_data["updated_at"]

    raw_bytes = json.dumps(memory_data, indent=2).encode("utf-8")
    if encryption_key:
        from storage.crypto import encrypt_bytes
        raw_bytes = encrypt_bytes(raw_bytes, encryption_key)

    file_path.write_bytes(raw_bytes)


def update_learning_order(context: UserContext, subject: str, new_order: List[str]) -> None:
    """Allow the student to manually override or adjust the computed learning order."""
    memory_data = load_subject_memory(context, subject)
    memory_data["learning_order"] = [t.strip() for t in new_order if t.strip()]
    save_subject_memory(context, subject, memory_data)


def list_user_memory_subjects(context: UserContext) -> List[str]:
    """List all subjects currently tracked in the user's memory folder."""
    subjects = []
    if context.memory_dir.exists():
        for file in context.memory_dir.glob("*.json"):
            try:
                with open(file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    name = data.get("subject", file.stem)
                    subjects.append(name)
            except Exception:
                subjects.append(file.stem)
    return sorted(subjects)


def delete_subject_memory(context: UserContext, subject: str) -> bool:
    """Delete a subject's JSON memory file."""
    file_path = get_memory_file_path(context, subject)
    if file_path.exists():
        file_path.unlink()
        return True
    return False
