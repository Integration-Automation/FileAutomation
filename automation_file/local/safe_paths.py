"""Path-traversal guard for local file operations.

``safe_join(root, user_path)`` returns the resolved absolute path only if it
lies under ``root`` once symlinks are followed; otherwise it raises
:class:`PathTraversalException`. The helper is intentionally independent of
any configuration module so callers can wrap individual operations instead of
opting in globally.
"""

from __future__ import annotations

import os
from pathlib import Path

from automation_file.exceptions import PathTraversalException


def safe_join(root: str | os.PathLike[str], user_path: str | os.PathLike[str]) -> Path:
    """Resolve ``user_path`` under ``root`` and guarantee containment.

    Raises :class:`PathTraversalException` if the resolved target would escape
    ``root`` through ``..`` components, an absolute path, or a symlink.
    """
    root_resolved = Path(root).resolve()
    candidate = Path(user_path)
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        resolved = (root_resolved / candidate).resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError as error:
        raise PathTraversalException(
            f"path {user_path!r} escapes root {str(root_resolved)!r}"
        ) from error
    return resolved


def is_within(root: str | os.PathLike[str], user_path: str | os.PathLike[str]) -> bool:
    """Return True if ``user_path`` resolves inside ``root``. Never raises."""
    try:
        safe_join(root, user_path)
    except PathTraversalException:
        return False
    return True
