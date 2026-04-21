"""Sphinx configuration for automation_file."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath("../.."))

project = "automation_file"
author = "JE-Chen"
copyright = "2026, JE-Chen"  # noqa: A001 - Sphinx requires this name
release = "0.0.31"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
    "myst_parser",
]

templates_path = ["_templates"]
exclude_patterns: list[str] = []
source_suffix = {".rst": "restructuredtext", ".md": "markdown"}

html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]

autodoc_default_options = {
    "members": True,
    "undoc-members": True,
    "show-inheritance": True,
}
autodoc_typehints = "description"
autodoc_mock_imports = [
    "google",
    "googleapiclient",
    "google_auth_oauthlib",
    "requests",
    "tqdm",
]

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
}
