"""StudyAssist main entry point launching local Gradio interface strictly bound to 127.0.0.1."""

import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# Import all tool modules to register them in agent dispatcher
import tools.ingest_material  # noqa: F401
import tools.search_notes     # noqa: F401
import tools.run_jury         # noqa: F401
import tools.generate_quiz    # noqa: F401
import tools.schedule_revision# noqa: F401
import tools.track_progress   # noqa: F401

from ui.dashboard import create_app


def main() -> None:
    """Launch StudyAssist interface bound strictly to localhost."""
    print("=======================================================")
    print("Starting StudyAssist — Agentic AI Study Assistant")
    print("Binding strictly to 127.0.0.1 (Localhost only, share=False)")
    print("=======================================================")
    
    app = create_app()
    app.launch(
        server_name="127.0.0.1",
        server_port=7860,
        share=False,
        show_error=True,
    )


if __name__ == "__main__":
    main()
