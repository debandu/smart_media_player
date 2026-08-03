"""
Tests for FileExplorer, its implementations, and ExploreFactory.

Structured in three layers so that adding an explorer for another platform
requires as little test surgery as possible:

1. Conformance — parameterised over every concrete implementation found in the
   package. A new explorer is picked up automatically, with no edit here.
2. Factory     — asserts the factory's *contract*, not which class it happens
   to return, so platform-detecting resolution does not break these.
3. Per-implementation behaviour — needs implementation-specific mocking, so
   each explorer gets its own class.
"""

import importlib
import inspect
import pkgutil

import pytest
from unittest.mock import patch

import FileExplorer as explorer_pkg
from FileExplorer.ExplorerFactory import ExploreFactory
from FileExplorer.TkinterFileExplorer import TkinterFileExplorer
from FileExplorer.FileExplorer import FileExplorer


def _concrete_explorers():
    """
    Every concrete FileExplorer implementation in the package.

    Discovered dynamically by importing each module under FileExplorer/, so an
    explorer added for Windows or Linux is covered by the conformance tests
    below without this file being touched.
    """
    for module in pkgutil.iter_modules(explorer_pkg.__path__):
        importlib.import_module(f"{explorer_pkg.__name__}.{module.name}")
    return [cls for cls in FileExplorer.__subclasses__() if not inspect.isabstract(cls)]


def _signature_params(cls, method_name):
    return list(inspect.signature(getattr(cls, method_name)).parameters)


CONCRETE_EXPLORERS = _concrete_explorers()

# HANDOVER.md defect #4 — TkinterFileExplorer.close() is declared without
# `self`, so calling it on an instance raises TypeError. Exempted here and
# pinned by test_known_close_signature_defect below.
KNOWN_BAD_SIGNATURES = {(TkinterFileExplorer, "close")}


# ---------------------------------------------------------------------------
# 1. Conformance — applies to every implementation, present and future
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("impl", CONCRETE_EXPLORERS, ids=lambda c: c.__name__)
class TestExplorerConformance:
    def test_subclasses_the_abc(self, impl):
        assert issubclass(impl, FileExplorer)

    def test_declares_required_attributes(self, impl):
        assert hasattr(impl, "open")
        assert hasattr(impl, "close")

    @pytest.mark.parametrize("method", ["open", "close"])
    def test_method_is_a_proper_instance_method(self, impl, method):
        """
        Every implementation's open()/close() must take `self`, or calling it on
        an instance raises TypeError.
        """
        if (impl, method) in KNOWN_BAD_SIGNATURES:
            pytest.skip(f"{impl.__name__}.{method}() — known defect, see HANDOVER.md #4")
        params = _signature_params(impl, method)
        assert params and params[0] == "self", (
            f"{impl.__name__}.{method}() is missing `self`"
        )

    def test_constructor_accepts_title_and_filetypes(self, impl):
        """main.py builds every explorer as Explorer(title=..., filetypes=...)."""
        params = _signature_params(impl, "__init__")
        assert "title" in params
        assert "filetypes" in params


def test_at_least_one_explorer_is_discoverable():
    """Guards the discovery helper itself — an empty list would silently pass everything."""
    assert CONCRETE_EXPLORERS, "no concrete FileExplorer implementations found"


def test_known_close_signature_defect():
    """
    Pins HANDOVER.md defect #4 so the exemption above cannot outlive the bug.

    When `TkinterFileExplorer.close()` is given a `self` parameter this test
    fails — at which point delete it and drop the entry from
    KNOWN_BAD_SIGNATURES.
    """
    assert _signature_params(TkinterFileExplorer, "close") == [], (
        "close() now takes self — remove this test and the KNOWN_BAD_SIGNATURES entry"
    )


# ---------------------------------------------------------------------------
# 2. Factory — contract, not identity
# ---------------------------------------------------------------------------

class TestExploreFactory:
    def test_tk_key_returns_the_tkinter_explorer(self):
        """The explicit "tk" key is a stable contract regardless of platform."""
        assert ExploreFactory.get_explorer("tk") is TkinterFileExplorer

    def test_unknown_name_still_returns_a_usable_explorer(self):
        """
        Deliberately does not assert *which* class. A factory that resolves by
        platform is a valid evolution; returning None or an abstract class is not.
        """
        cls = ExploreFactory.get_explorer("nonexistent")
        assert cls is not None
        assert issubclass(cls, FileExplorer)
        assert not inspect.isabstract(cls)

    def test_returns_a_class_not_an_instance(self, ):
        """main.py calls the result with constructor args, so it must be a class."""
        cls = ExploreFactory.get_explorer("tk")
        assert inspect.isclass(cls)


# ---------------------------------------------------------------------------
# 3. TkinterFileExplorer behaviour
# ---------------------------------------------------------------------------

class TestTkinterFileExplorer:
    @pytest.fixture
    def explorer(self):
        with patch("FileExplorer.TkinterFileExplorer.Tk"), \
             patch("FileExplorer.TkinterFileExplorer.tkinter.Frame"):
            yield TkinterFileExplorer(
                title="Pick a Video",
                filetypes=[("Videos", "*.mp4 *.mov")],
            )

    def test_stores_title(self, explorer):
        assert explorer.title == "Pick a Video"

    def test_stores_filetypes(self, explorer):
        assert explorer.filetypes == [("Videos", "*.mp4 *.mov")]

    def test_open_returns_selected_path(self, explorer):
        with patch("FileExplorer.TkinterFileExplorer.filedialog.askopenfilename",
                   return_value="/videos/clip.mp4"):
            assert explorer.open() == "/videos/clip.mp4"

    def test_open_returns_empty_string_when_cancelled(self, explorer):
        with patch("FileExplorer.TkinterFileExplorer.filedialog.askopenfilename",
                   return_value=""):
            assert explorer.open() == ""

    def test_open_forwards_title_and_filetypes_to_the_dialog(self, explorer):
        with patch("FileExplorer.TkinterFileExplorer.filedialog.askopenfilename",
                   return_value="") as mock_dialog:
            explorer.open()
        _, kwargs = mock_dialog.call_args
        assert kwargs["title"] == "Pick a Video"
        assert kwargs["filetypes"] == [("Videos", "*.mp4 *.mov")]
