"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def sample_file(tmp_path: Path) -> Path:
    """Return a throw-away text file inside tmp_path."""
    path = tmp_path / "sample.txt"
    path.write_text("hello world", encoding="utf-8")
    return path


@pytest.fixture
def sample_dir(tmp_path: Path) -> Path:
    """Return a tmp directory pre-populated with a handful of files."""
    root = tmp_path / "sample_dir"
    root.mkdir()
    (root / "a.txt").write_text("a", encoding="utf-8")
    (root / "b.txt").write_text("b", encoding="utf-8")
    (root / "c.log").write_text("c", encoding="utf-8")
    nested = root / "nested"
    nested.mkdir()
    (nested / "d.txt").write_text("d", encoding="utf-8")
    return root


@pytest.fixture(scope="session")
def qt_app():
    """Keep one application alive until every GUI module has released its widgets."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    widgets = pytest.importorskip("PySide6.QtWidgets")
    app = widgets.QApplication.instance() or widgets.QApplication([])
    yield app
    app.closeAllWindows()
    app.processEvents()
    app.shutdown()
