"""tar / tar.gz / tar.bz2 / tar.xz archive operations.

Both ``create_tar`` and ``extract_tar`` refuse archives / targets that escape
the intended root using :func:`safe_join`, and ``extract_tar`` additionally
rejects archive members whose names, symlinks, or hardlinks would write
outside the target directory.
"""

from __future__ import annotations

import tarfile
from pathlib import Path
from typing import Literal

from automation_file.exceptions import FileAutomationException, PathTraversalException
from automation_file.local.safe_paths import is_within
from automation_file.logging_config import file_automation_logger

_WriteMode = Literal["w", "w:gz", "w:bz2", "w:xz"]
_COMPRESSIONS: dict[str | None, _WriteMode] = {
    None: "w",
    "": "w",
    "none": "w",
    "gz": "w:gz",
    "bz2": "w:bz2",
    "xz": "w:xz",
}


class TarException(FileAutomationException):
    """Raised when tar creation or extraction fails."""


def create_tar(
    source: str,
    target: str,
    *,
    compression: str | None = "gz",
) -> str:
    """Create a tar archive at ``target`` containing ``source``.

    ``compression`` is one of ``None`` / ``"none"`` / ``"gz"`` / ``"bz2"`` /
    ``"xz"``. The archive member names are relative to ``source`` — the
    directory itself is the top-level member.
    """
    key = (compression or "").lower() if isinstance(compression, str) else None
    if key not in _COMPRESSIONS:
        raise TarException(f"unknown compression: {compression!r}")
    mode = _COMPRESSIONS[key]

    src_path = Path(source)
    if not src_path.exists():
        raise TarException(f"source not found: {source}")
    target_path = Path(target)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with tarfile.open(str(target_path), mode) as archive:
            archive.add(str(src_path), arcname=src_path.name)
    except (OSError, tarfile.TarError) as err:
        raise TarException(f"create_tar failed: {err}") from err

    file_automation_logger.info("create_tar: %s -> %s (%s)", source, target, mode)
    return str(target_path)


def extract_tar(source: str, target_dir: str) -> list[str]:
    """Extract archive ``source`` into ``target_dir``; reject traversal attempts."""
    src_path = Path(source)
    if not src_path.is_file():
        raise TarException(f"archive not found: {source}")
    dest = Path(target_dir)
    dest.mkdir(parents=True, exist_ok=True)

    extracted: list[str] = []
    try:
        with tarfile.open(str(src_path), "r:*") as archive:
            _verify_members(archive, dest)
            for member in archive.getmembers():
                archive.extract(member, str(dest), filter="data")
                extracted.append(member.name)
    except PathTraversalException:
        raise
    except (OSError, tarfile.TarError) as err:
        raise TarException(f"extract_tar failed: {err}") from err

    file_automation_logger.info("extract_tar: %s -> %s (%d)", source, target_dir, len(extracted))
    return extracted


def _verify_members(archive: tarfile.TarFile, dest: Path) -> None:
    dest_resolved = dest.resolve()
    for member in archive.getmembers():
        candidate = (dest_resolved / member.name).resolve()
        if not is_within(str(dest_resolved), str(candidate)):
            raise PathTraversalException(f"tar member escapes target: {member.name}")
        if member.issym() or member.islnk():
            link = member.linkname
            link_path = (
                (dest_resolved / link).resolve()
                if not Path(link).is_absolute()
                else Path(link).resolve()
            )
            if not is_within(str(dest_resolved), str(link_path)):
                raise PathTraversalException(
                    f"tar {('symlink' if member.issym() else 'hardlink')} escapes target: "
                    f"{member.name} -> {link}"
                )
