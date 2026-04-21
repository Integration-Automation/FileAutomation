"""Directory-tree manifests — JSON snapshot of every file's checksum.

A manifest is a simple JSON document recording every file under a root,
its size, and a streaming digest (SHA-256 by default). Two operations::

    write_manifest(root, manifest_path)  # snapshot now
    verify_manifest(root, manifest_path) # verify the tree still matches

Use cases: release-artifact verification, backup integrity checks, detecting
tampering on a sync target, or pre-flight checks before a rename / move.

The document shape is intentionally small and human-readable::

    {
      "version": 1,
      "algorithm": "sha256",
      "root": "/abs/path/at/snapshot/time",
      "created_at": "2026-04-21T10:15:30+00:00",
      "files": {
        "a.txt":            {"size": 3,      "checksum": "..."},
        "nested/b.txt":     {"size": 1_024,  "checksum": "..."}
      }
    }

Paths in the ``files`` mapping are POSIX-style (forward-slash) relative
paths so the manifest round-trips across Windows and Unix.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Any

from automation_file.core.checksum import file_checksum
from automation_file.exceptions import DirNotExistsException, FileAutomationException
from automation_file.logging_config import file_automation_logger

_MANIFEST_VERSION = 1
_DEFAULT_ALGO = "sha256"


class ManifestException(FileAutomationException):
    """Raised for invalid manifest documents or unreadable manifest paths."""


def write_manifest(
    root: str | os.PathLike[str],
    manifest_path: str | os.PathLike[str],
    *,
    algorithm: str = _DEFAULT_ALGO,
) -> dict[str, Any]:
    """Write a manifest for every file under ``root``. Returns the manifest dict."""
    root_path = Path(root)
    if not root_path.is_dir():
        raise DirNotExistsException(str(root_path))
    files: dict[str, dict[str, Any]] = {}
    for relative in _walk_files(root_path):
        absolute = root_path / relative
        files[_posix_rel(relative)] = {
            "size": absolute.stat().st_size,
            "checksum": file_checksum(absolute, algorithm=algorithm),
        }
    manifest: dict[str, Any] = {
        "version": _MANIFEST_VERSION,
        "algorithm": algorithm,
        "root": str(root_path.resolve()),
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "files": files,
    }
    Path(manifest_path).parent.mkdir(parents=True, exist_ok=True)
    Path(manifest_path).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    file_automation_logger.info(
        "write_manifest: %d files under %s -> %s", len(files), root_path, manifest_path
    )
    return manifest


def verify_manifest(
    root: str | os.PathLike[str],
    manifest_path: str | os.PathLike[str],
) -> dict[str, Any]:
    """Verify every file recorded in ``manifest_path`` still matches under ``root``.

    Returns a summary dict::

        {
            "matched":  ["a.txt"],
            "missing":  ["gone.txt"],
            "modified": ["changed.txt"],
            "extra":    ["new.txt"],    # present under root, not in manifest
            "ok": False,
        }

    ``ok`` is True iff ``missing`` and ``modified`` are both empty (extras
    are reported but do not fail verification — mirror ``sync_dir``'s
    default non-deleting posture).
    """
    root_path = Path(root)
    if not root_path.is_dir():
        raise DirNotExistsException(str(root_path))
    manifest = _load_manifest(manifest_path)
    algorithm = manifest.get("algorithm", _DEFAULT_ALGO)
    recorded = manifest.get("files") or {}

    summary: dict[str, Any] = {
        "matched": [],
        "missing": [],
        "modified": [],
        "extra": [],
        "ok": False,
    }

    for rel, meta in recorded.items():
        _verify_one(root_path, rel, meta, algorithm, summary)

    recorded_keys = set(recorded.keys())
    for rel_path in _walk_files(root_path):
        posix = _posix_rel(rel_path)
        if posix not in recorded_keys:
            summary["extra"].append(posix)

    summary["ok"] = not summary["missing"] and not summary["modified"]
    file_automation_logger.info(
        "verify_manifest: ok=%s matched=%d missing=%d modified=%d extra=%d",
        summary["ok"],
        len(summary["matched"]),
        len(summary["missing"]),
        len(summary["modified"]),
        len(summary["extra"]),
    )
    return summary


def _verify_one(
    root: Path,
    relative: str,
    meta: dict[str, Any],
    algorithm: str,
    summary: dict[str, Any],
) -> None:
    target = root / relative
    if not target.is_file():
        summary["missing"].append(relative)
        return
    expected = meta.get("checksum")
    size = meta.get("size")
    if isinstance(size, int) and target.stat().st_size != size:
        summary["modified"].append(relative)
        return
    if not isinstance(expected, str) or file_checksum(target, algorithm=algorithm) != expected:
        summary["modified"].append(relative)
        return
    summary["matched"].append(relative)


def _load_manifest(path: str | os.PathLike[str]) -> dict[str, Any]:
    manifest_path = Path(path)
    if not manifest_path.is_file():
        raise ManifestException(f"manifest not found: {manifest_path}")
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        raise ManifestException(f"cannot read manifest {manifest_path}: {err}") from err
    if not isinstance(data, dict) or "files" not in data:
        raise ManifestException(f"manifest missing 'files' mapping: {manifest_path}")
    return data


def _walk_files(root: Path) -> list[Path]:
    entries: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames.sort()
        base = Path(dirpath)
        for name in sorted(filenames):
            entries.append((base / name).relative_to(root))
    return entries


def _posix_rel(relative: Path) -> str:
    return str(relative).replace("\\", "/")
