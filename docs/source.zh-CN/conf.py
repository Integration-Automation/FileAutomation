"""Sphinx 配置（简体中文）。"""

# pylint: disable=invalid-name  # Sphinx 要求使用这些特定小写名称。

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath("../.."))

project = "automation_file"
author = "JE-Chen"
copyright = "2026, JE-Chen"  # pylint: disable=redefined-builtin
release = "0.0.32"
language = "zh_CN"
html_title = "automation_file 文档（简体中文）"

# Read the Docs sets READTHEDOCS_CANONICAL_URL to the per-translation canonical
# URL (e.g. https://fileautomation.readthedocs.io/zh_CN/latest/). Use it as the
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

templates_path = ["../source/_templates"]
exclude_patterns: list[str] = []
source_suffix = {".rst": "restructuredtext", ".md": "markdown"}

html_theme = "sphinx_rtd_theme"
html_static_path = ["../source/_static"]

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
