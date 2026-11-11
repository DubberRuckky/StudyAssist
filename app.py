"""StudyAssist main entry point launching local Gradio interface strictly bound to 127.0.0.1."""

import os
import subprocess
import sys

# If run directly outside the virtual environment, automatically relaunch with the project's .venv
if __name__ == "__main__":
    _root_dir = os.path.abspath(os.path.dirname(__file__))
    _scripts_dir = "Scripts" if os.name == "nt" else "bin"
    _py_name = "python.exe" if os.name == "nt" else "python"
    _venv_py = os.path.join(_root_dir, ".venv", _scripts_dir, _py_name)
    if os.path.exists(_venv_py) and os.path.abspath(sys.executable).lower() != os.path.abspath(_venv_py).lower():
        print(f"[*] Switching to project virtual environment: {_venv_py}")
        sys.exit(subprocess.call([_venv_py] + sys.argv))

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# Startup dependency check before heavy imports
_REQUIRED_PACKAGES = [
    ("requests", "requests"),
    ("pydantic", "pydantic"),
    ("argon2", "argon2-cffi"),
    ("cryptography", "cryptography"),
    ("keyring", "keyring"),
    ("psutil", "psutil"),
    ("litellm", "litellm"),
    ("chromadb", "chromadb"),
    ("pymupdf", "pymupdf"),
    ("docx", "python-docx"),
    ("pptx", "python-pptx"),
    ("openpyxl", "openpyxl"),
    ("pytesseract", "pytesseract"),
    ("PIL", "Pillow"),
    ("gradio", "gradio"),
]


def _check_startup_dependencies() -> None:
    """Verify that all required packages can be imported before heavy imports."""
    import importlib

    missing = []
    for mod_name, pkg_name in _REQUIRED_PACKAGES:
        try:
            if mod_name == "pymupdf":
                try:
                    importlib.import_module("pymupdf")
                except ImportError:
                    importlib.import_module("fitz")
            else:
                importlib.import_module(mod_name)
        except ImportError:
            if pkg_name not in missing:
                missing.append(pkg_name)

    if missing:
        install_cmd = f'"{sys.executable}" -m pip install -r requirements.txt'
        print("=" * 65, file=sys.stderr)
        print("[StudyAssist] ERROR: Missing required dependencies!", file=sys.stderr)
        print("The following required packages could not be imported:", file=sys.stderr)
        for pkg in missing:
            print(f"  - {pkg}", file=sys.stderr)
        print(f"\nInterpreter in use:\n  {sys.executable}", file=sys.stderr)
        print(f"\nTo install the missing dependencies, run:\n  {install_cmd}", file=sys.stderr)
        print("=" * 65, file=sys.stderr)
        sys.exit(1)


_check_startup_dependencies()

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
