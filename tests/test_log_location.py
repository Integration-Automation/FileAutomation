"""Where FileAutomation's log goes, and that importing the package writes nothing (workspace item X-6)."""

import logging
import os
import subprocess  # nosec B404 - the import is exercised in a fresh interpreter
import sys
import warnings
from pathlib import Path

from automation_file import logging_config as loggin_instance
from automation_file.logging_config import LOG_FILE_ENV, FileAutomationFileHandler, default_log_file

MODULE_FILE = Path(loggin_instance.__file__)

# Load just this module in a fresh interpreter (skipping the package __init__), then list
# the working directory.
_IMPORT_ONLY = (
    "import importlib.util, os, sys\n"
    "spec = importlib.util.spec_from_file_location('probe', sys.argv[1])\n"
    "spec.loader.exec_module(importlib.util.module_from_spec(spec))\n"
    "print(sorted(os.listdir('.')))\n"
)


def _log(handler: logging.Handler, message: str) -> None:
    log = logging.getLogger(f"test_log_location.{id(handler)}")
    log.propagate = False
    log.setLevel(logging.DEBUG)
    log.addHandler(handler)
    try:
        log.warning(message)
    finally:
        log.removeHandler(handler)
        handler.close()


def test_default_is_under_the_home_directory(monkeypatch, tmp_path):
    monkeypatch.delenv(LOG_FILE_ENV, raising=False)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    assert default_log_file() == tmp_path / ".automation_file" / "logs" / "FileAutomation.log"


def test_environment_variable_overrides_the_location(monkeypatch, tmp_path):
    monkeypatch.setenv(LOG_FILE_ENV, str(tmp_path / "custom.log"))
    assert default_log_file() == tmp_path / "custom.log"


def test_importing_writes_no_file(tmp_path):
    target = tmp_path / "home" / "FileAutomation.log"
    env = {key: value for key, value in os.environ.items() if key != LOG_FILE_ENV}
    env[LOG_FILE_ENV] = str(target)
    result = subprocess.run(  # nosec B603 - fixed interpreter, test-controlled arguments
        [sys.executable, "-c", _IMPORT_ONLY, str(MODULE_FILE)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"
    assert not target.parent.exists()


def test_first_record_creates_the_directory_and_later_handlers_append(tmp_path):
    target = tmp_path / "nested" / "FileAutomation.log"
    _log(FileAutomationFileHandler(str(target)), "first")
    _log(FileAutomationFileHandler(str(target)), "second 中文 ⠐ \udcff")
    text = target.read_text(encoding="utf-8")
    assert "first" in text and "second 中文 ⠐" in text and "\\udcff" in text


def test_an_unopenable_path_only_warns(tmp_path):
    blocker = tmp_path / "a_file"
    blocker.write_text("x", encoding="utf-8")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _log(FileAutomationFileHandler(str(blocker / "FileAutomation.log")), "goes nowhere")
    assert any(issubclass(item.category, RuntimeWarning) for item in caught)
