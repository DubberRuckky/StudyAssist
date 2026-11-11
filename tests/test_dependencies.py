"""Automated dependency and module import tests.

Verifies:
1. Every project module in the repository can be imported without errors.
2. Every third-party package imported anywhere in the code is declared in requirements.txt.
"""

import ast
import importlib
from pathlib import Path
import re
import sys
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Known package name mappings where import name differs from distribution/install name
IMPORT_TO_PKG_MAP = {
    "fitz": "pymupdf",
    "docx": "python-docx",
    "pptx": "python-pptx",
    "PIL": "Pillow",
    "argon2": "argon2-cffi",
}

# Root packages that belong to this project
PROJECT_PACKAGES = {
    "agent",
    "auth",
    "config",
    "models",
    "storage",
    "tools",
    "ui",
    "tests",
    "app",
}


def test_import_every_project_module():
    """Verify that every python module within the project can be imported successfully."""
    failed_imports = {}

    # Ensure project root is in sys.path
    root_str = str(PROJECT_ROOT)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)

    modules_to_test = []

    # Collect project packages
    for pkg in ["agent", "auth", "config", "models", "storage", "tools", "ui"]:
        pkg_dir = PROJECT_ROOT / pkg
        if not pkg_dir.is_dir():
            continue
        for py_path in pkg_dir.rglob("*.py"):
            rel_parts = py_path.relative_to(PROJECT_ROOT).with_suffix("").parts
            mod_name = ".".join(rel_parts)
            modules_to_test.append(mod_name)

    # Add root app module
    if (PROJECT_ROOT / "app.py").exists():
        modules_to_test.append("app")

    for mod_name in sorted(modules_to_test):
        try:
            importlib.import_module(mod_name)
        except Exception as exc:
            failed_imports[mod_name] = str(exc)

    assert not failed_imports, (
        f"The following {len(failed_imports)} project module(s) failed to import:\n"
        + "\n".join(f"  - {mod}: {err}" for mod, err in failed_imports.items())
    )


def test_requirements_covers_all_third_party_imports():
    """Verify that requirements.txt declares every third-party package imported in the codebase."""
    req_file = PROJECT_ROOT / "requirements.txt"
    assert req_file.exists(), "requirements.txt must exist at project root."

    # Parse declared packages from requirements.txt
    declared_pkgs = set()
    for line in req_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Strip version specifiers like >=, ==, <=, ~=, !=
        pkg_name = re.split(r"[<>=!~]", line)[0].strip().lower()
        if pkg_name:
            declared_pkgs.add(pkg_name)

    # Standard library module names
    stdlib_modules = sys.stdlib_module_names

    # Collect all .py files in project, excluding virtual environments and cache
    py_files = []
    ignored_parts = {
        ".venv",
        "venv",
        ".git",
        "__pycache__",
        "build",
        "dist",
        ".pytest_cache",
        "Lib",
        "lib",
        "Include",
        "Scripts",
        "site-packages",
    }
    for py_path in PROJECT_ROOT.rglob("*.py"):
        parts = py_path.relative_to(PROJECT_ROOT).parts
        if any(part in ignored_parts for part in parts):
            continue
        py_files.append(py_path)

    missing_dependencies = {}

    for py_file in py_files:
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        except Exception as exc:
            pytest.fail(f"Failed to parse AST for {py_file}: {exc}")

        for node in ast.walk(tree):
            top_module = None
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top_module = alias.name.split(".")[0]
                    _check_import(top_module, py_file, stdlib_modules, declared_pkgs, missing_dependencies)
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    top_module = node.module.split(".")[0]
                    _check_import(top_module, py_file, stdlib_modules, declared_pkgs, missing_dependencies)


    assert not missing_dependencies, (
        f"Found {len(missing_dependencies)} third-party package(s) imported in code but missing from requirements.txt:\n"
        + "\n".join(
            f"  - {pkg} (imported in: {', '.join(sorted(str(f.relative_to(PROJECT_ROOT)) for f in files))})"
            for pkg, files in sorted(missing_dependencies.items())
        )
    )


def _check_import(top_module, py_file, stdlib_modules, declared_pkgs, missing_dependencies):
    if not top_module:
        return
    # Skip stdlib and internal project modules
    if top_module in stdlib_modules or top_module in PROJECT_PACKAGES:
        return

    # Map import alias to distribution package name
    canonical_pkg = IMPORT_TO_PKG_MAP.get(top_module, top_module).lower()

    if canonical_pkg not in declared_pkgs:
        missing_dependencies.setdefault(canonical_pkg, set()).add(py_file)
