"""
Shared fixtures for the test suite.

Two problems make this project awkward to test, and both are solved here rather
than by duplicating production logic into the tests:

1. `main.py` executes at module level (opens a file dialog, spawns threads,
   enters the Qt event loop), so it cannot be imported. Rather than re-implement
   `_parse_seconds` in the tests — which would mean testing a copy that can
   silently diverge from the real function — we extract that one function from
   the source with `ast` and compile it in isolation.

2. Qt needs a display. We select the `offscreen` platform plugin before PySide6
   is imported anywhere, so real Qt objects can be constructed headlessly.
"""

import ast
import os
import pathlib

import pytest

# Must be set before PySide6 is imported by any test module.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Qt
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def qapp():
    """A single QApplication for the whole session; Qt allows only one."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


# ---------------------------------------------------------------------------
# main.py — extract the real function without executing the module
# ---------------------------------------------------------------------------

def _extract_function(source_path: pathlib.Path, name: str, imports: tuple[str, ...] = ()):
    """
    Compile a single top-level function out of a Python file, skipping every
    other statement in it.

    This gives the tests the *real* function object, so a change to the source
    is picked up automatically instead of silently drifting from a copy.
    """
    tree = ast.parse(source_path.read_text())
    try:
        func = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == name
        )
    except StopIteration:
        raise AssertionError(
            f"{name}() no longer exists in {source_path.name} — update the tests."
        ) from None

    body = [ast.Import(names=[ast.alias(name=mod)]) for mod in imports] + [func]
    module = ast.Module(body=body, type_ignores=[])
    ast.fix_missing_locations(module)

    namespace: dict = {}
    exec(compile(module, str(source_path), "exec"), namespace)
    return namespace[name]


@pytest.fixture(scope="session")
def parse_seconds():
    """The real `_parse_seconds` from main.py."""
    return _extract_function(PROJECT_ROOT / "main.py", "_parse_seconds", imports=("re",))
