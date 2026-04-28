"""Sphinx configuration for automation_file."""

# pylint: disable=invalid-name  # Sphinx requires these specific lowercase names.

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath("../.."))

project = "automation_file"
author = "JE-Chen"
copyright = "2026, JE-Chen"  # pylint: disable=redefined-builtin  # Sphinx requires this name
release = "0.0.32"
language = "en"

# Read the Docs sets READTHEDOCS_CANONICAL_URL to the per-translation canonical
# URL (e.g. https://fileautomation.readthedocs.io/en/latest/). Use it as the
# base URL so canonical <link rel="canonical"> tags and the translations flyout
# resolve correctly. Empty string off-RTD.
html_baseurl = os.environ.get("READTHEDOCS_CANONICAL_URL", "")

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
    "myst_parser",
    "sphinxcontrib.mermaid",
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
    "boto3",
    "azure",
    "dropbox",
    "paramiko",
]

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
}
