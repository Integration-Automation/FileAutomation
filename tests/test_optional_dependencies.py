"""The base install needs no cloud SDK and no GUI toolkit; each lives in an extra.

Three things are held here:

* ``import automation_file`` succeeds when every optional package is impossible to
  import, and builds the whole action registry;
* it loads none of them even when they are installed;
* the extras in ``stable.toml`` / ``dev.toml`` match what the code asks for, and no
  optional package sits among the base dependencies.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from automation_file.core.optional import EXTRAS, install_hint, require_module
from automation_file.exceptions import FileAutomationException, OptionalDependencyException

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # declared in *.toml for Python<3.11

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Top-level import names of every package that only an extra installs.
OPTIONAL_ROOTS = (
    "boto3",
    "botocore",
    "azure",
    "dropbox",
    "paramiko",
    "googleapiclient",
    "google_auth_oauthlib",
    "google_auth_httplib2",
    "msal",
    "box_sdk_gen",
    "boxsdk",
    "pyarrow",
    "fsspec",
    "smbclient",
    "smbprotocol",
    "PySide6",
)
#: Distribution names that must never be base dependencies.
OPTIONAL_DISTRIBUTIONS = {
    "boto3",
    "azure-storage-blob",
    "dropbox",
    "paramiko",
    "google-api-python-client",
    "google-auth-httplib2",
    "google-auth-oauthlib",
    "msal",
    "boxsdk",
    "pyarrow",
    "fsspec",
    "smbprotocol",
    "pyside6",
}

_PROBE = """
import importlib, importlib.abc, json, sys

blocked = set(json.loads(sys.argv[1]))


class Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in blocked:
            raise ImportError("blocked: " + fullname)
        return None


if blocked:
    sys.meta_path.insert(0, Blocker())
import automation_file
from automation_file.exceptions import FileAutomationException, OptionalDependencyException


def client(backend):
    return importlib.import_module("automation_file.remote." + backend + ".client")


# What the import itself pulled in, measured before any feature is used.
loaded = sorted({name.split(".")[0] for name in sys.modules} & set(json.loads(sys.argv[2])))
messages = {}
features = {
    "s3": lambda: automation_file.s3_instance.later_init(),
    "azure": lambda: automation_file.azure_blob_instance.later_init(connection_string="x"),
    "dropbox": lambda: automation_file.dropbox_instance.later_init("token"),
    "gdrive": lambda: automation_file.drive_search_all_file(),
    "sftp": lambda: client("sftp")._import_paramiko(),
    "onedrive": lambda: client("onedrive")._import_msal(),
    "smb": lambda: client("smb")._import_smbclient(),
}
for name, call in features.items() if blocked else ():
    try:
        call()
    except OptionalDependencyException as error:
        messages[name] = str(error)
    except FileAutomationException as error:
        # A client with an exception type of its own keeps it, and adds the hint.
        messages[name] = str(error)
    except Exception as error:
        messages[name] = "OTHER " + type(error).__name__
    else:
        messages[name] = "NO ERROR"
print(json.dumps({
    "commands": len(automation_file.executor.registry.event_dict),
    "loaded": loaded,
    "messages": messages,
}))
"""


def _probe(blocked: tuple[str, ...]) -> dict:
    result = subprocess.run(  # nosec B603 - fixed argv: this interpreter and a script defined above
        [sys.executable, "-c", _PROBE, json.dumps(blocked), json.dumps(OPTIONAL_ROOTS)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_the_package_imports_without_any_optional_dependency() -> None:
    report = _probe((*OPTIONAL_ROOTS, "google"))
    assert report["commands"] > 100
    assert report["loaded"] == []
    for extra in ("s3", "azure", "dropbox", "gdrive", "sftp", "onedrive", "smb"):
        assert install_hint(extra) in report["messages"][extra], report["messages"]


def test_importing_the_package_loads_no_optional_dependency() -> None:
    report = _probe(())
    assert report["loaded"] == []


def test_require_module_returns_the_module_or_names_the_extra() -> None:
    assert require_module("json", extra="s3").dumps({}) == "{}"
    with pytest.raises(OptionalDependencyException) as caught:
        require_module("no_such_sdk_for_automation_file.sub", extra="s3")
    message = str(caught.value)
    assert message.startswith("no_such_sdk_for_automation_file is not installed; the S3 backend")
    assert message.endswith('pip install "automation_file[s3]"')
    assert isinstance(caught.value, FileAutomationException)
    assert isinstance(caught.value, RuntimeError)
    assert isinstance(caught.value.__cause__, ImportError)
    with pytest.raises(OptionalDependencyException, match="the reports feature"):
        require_module("no_such_sdk_for_automation_file", extra="reports")


def _name(requirement: str) -> str:
    return re.split(r"[<>=!~;\[ ]", requirement, maxsplit=1)[0].strip().lower().replace("_", "-")


@pytest.fixture(params=["stable.toml", "dev.toml"])
def project(request: pytest.FixtureRequest) -> dict:
    with (REPO_ROOT / request.param).open("rb") as handle:
        return tomllib.load(handle)["project"]


def test_no_optional_package_is_a_base_dependency(project: dict) -> None:
    base = {_name(requirement) for requirement in project["dependencies"]}
    assert base & OPTIONAL_DISTRIBUTIONS == set()


def test_every_extra_the_code_names_is_declared(project: dict) -> None:
    extras = project["optional-dependencies"]
    assert set(EXTRAS) <= set(extras)
    assert {"all", "test", "dev"} <= set(extras)


def test_all_is_the_union_of_the_feature_extras(project: dict) -> None:
    extras = project["optional-dependencies"]
    union = {requirement for name in EXTRAS for requirement in extras[name]}
    assert set(extras["all"]) == union
    assert {_name(requirement) for requirement in union} == OPTIONAL_DISTRIBUTIONS


def test_the_extras_that_need_nothing_are_empty(project: dict) -> None:
    extras = project["optional-dependencies"]
    assert extras["ftp"] == []
    assert extras["webdav"] == []
