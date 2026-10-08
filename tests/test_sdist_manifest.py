"""The source distributions carry no test suite.

Package discovery keeps ``tests`` out of the wheels (``test_dev_toml_parity.py``), but setuptools
adds ``tests/test*.py`` to an sdist by default whatever discovery says. ``MANIFEST.in`` prunes the
directory for both channels. The file is read as text: nothing is built at test time.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_DIRECTORY = Path(__file__).resolve().parent.name
# MANIFEST.in commands that put files into the sdist.
ADDING = {"include", "recursive-include", "global-include", "graft"}


def _commands() -> list[list[str]]:
    """Return each ``MANIFEST.in`` command as its words, without comments and blank lines."""
    lines = (REPO_ROOT / "MANIFEST.in").read_text(encoding="utf-8").splitlines()
    return [line.split() for line in lines if line.strip() and not line.lstrip().startswith("#")]


def test_sdist_prunes_the_test_directory():
    assert ["prune", TEST_DIRECTORY] in _commands()


def test_nothing_puts_the_tests_back():
    # Commands apply in order, so only one that adds files after the prune could bring tests back.
    commands = _commands()
    after_prune = commands[commands.index(["prune", TEST_DIRECTORY]) + 1 :]
    assert [command for command in after_prune if command[0] in ADDING] == []
