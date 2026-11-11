"""UserContext object defining the execution scope and isolated paths for a logged-in user."""

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class UserContext:
    """Immutable user execution context holding isolated paths and identity."""

    user_id: str
    username: str
    display_name: str
    base_dir: Path
    db_path: Path
    chroma_dir: Path
    memory_dir: Path
    uploads_dir: Path
    logs_dir: Path
    extra_metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(cls, user_id: str, username: str, display_name: Optional[str] = None, data_root: Optional[Path] = None) -> "UserContext":
        """Instantiate UserContext and initialize user-isolated directory hierarchy."""
        root = data_root or (Path(__file__).resolve().parent.parent / "data")
        user_folder = (root / "users" / user_id).resolve()

        # Initialize subdirectories
        chroma_folder = user_folder / "chroma"
        memory_folder = user_folder / "memory"
        uploads_folder = user_folder / "uploads"
        logs_folder = user_folder / "logs"

        for directory in [user_folder, chroma_folder, memory_folder, uploads_folder, logs_folder]:
            directory.mkdir(parents=True, exist_ok=True)

        return cls(
            user_id=user_id,
            username=username,
            display_name=display_name or username,
            base_dir=user_folder,
            db_path=user_folder / "study.db",
            chroma_dir=chroma_folder,
            memory_dir=memory_folder,
            uploads_dir=uploads_folder,
            logs_dir=logs_folder,
        )

    def resolve_safe_path(self, relative_path: str | Path) -> Path:
        """Resolve a candidate path and reject any attempts at directory traversal."""
        candidate = (self.base_dir / relative_path).resolve()
        base_resolved = self.base_dir.resolve()

        # Verify that candidate is within the user's isolated base directory
        try:
            candidate.relative_to(base_resolved)
        except ValueError:
            raise PermissionError(
                f"Path traversal access denied: '{relative_path}' resolves outside user boundary."
            )

        return candidate

    def purge_user_data(self) -> None:
        """Purge all files and folders associated with this user upon account deletion."""
        if self.base_dir.exists():
            shutil.rmtree(self.base_dir, ignore_errors=True)
