"""Optional dependencies: import an SDK when a feature needs it, or say which extra to install.

The base install carries no cloud SDK and no GUI toolkit. Each backend's SDK
lives in an extra (``pip install "automation_file[s3]"``), and the code that
needs it calls :func:`require_module` at the moment of use, so importing
``automation_file`` never depends on a package the user did not ask for.
"""

from __future__ import annotations

import importlib
from types import ModuleType

from automation_file.exceptions import OptionalDependencyException

#: Extra name -> what it enables, for messages and documentation.
EXTRAS: dict[str, str] = {
    "s3": "the S3 backend",
    "azure": "the Azure Blob backend",
    "gdrive": "the Google Drive backend",
    "dropbox": "the Dropbox backend",
    "sftp": "the SFTP backend",
    "ftp": "the FTP / FTPS backend",
    "webdav": "the WebDAV backend",
    "smb": "the SMB / CIFS backend",
    "fsspec": "the fsspec bridge and adapter",
    "onedrive": "the OneDrive backend",
    "box": "the Box backend",
    "parquet": "the Parquet data operations",
    "gui": "the desktop GUI",
}
_DISTRIBUTION = "automation_file"


def install_hint(extra: str) -> str:
    """Return the ``pip install`` command that provides ``extra``."""
    return f'pip install "{_DISTRIBUTION}[{extra}]"'


def require_module(name: str, *, extra: str) -> ModuleType:
    """Import and return the module ``name``, which the extra ``extra`` provides.

    Raises :class:`OptionalDependencyException` naming the extra when the module
    cannot be imported.
    """
    try:
        # nosemgrep  # callers pass the literal name of an optional SDK, never input from outside
        return importlib.import_module(name)
    except ImportError as error:
        feature = EXTRAS.get(extra, f"the {extra} feature")
        raise OptionalDependencyException(
            f"{name.partition('.')[0]} is not installed; {feature} needs it: {install_hint(extra)}"
        ) from error
