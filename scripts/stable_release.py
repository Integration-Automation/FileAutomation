"""Pick the version of a stable release of ``automation_file``.

The ``publish`` job of ``.github/workflows/publish.yml`` runs it on a push to ``main``::

    python scripts/stable_release.py bump

For ``stable.toml`` and for ``dev.toml`` it decides between two cases:

* **A patch release**, the usual one: the patch number goes up by one.
* **A minor or major release**: a pull request raises ``MAJOR`` or ``MINOR`` by writing
  the version it wants (``1.1.0``, ``2.0.0``) in the file. When the file's ``MAJOR.MINOR``
  is above the newest release tag's, the version in the file is the release and nothing is
  added to it.

The stable version must end up above the newest ``vX.Y.Z`` tag; anything else stops the
job before it builds. The two versions are written to ``$GITHUB_OUTPUT`` as ``new_version``
and ``dev_version``.
"""

from __future__ import annotations

import os
import re
import subprocess  # nosec B404  # one fixed git command, no shell
import sys
from collections.abc import Iterable
from pathlib import Path

Version = tuple[int, int, int]

VERSION_LINE = re.compile(r'^(version\s*=\s*)"(\d+)\.(\d+)\.(\d+)"', re.MULTILINE)
TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
GIT_TIMEOUT_SECONDS = 60
STABLE = "stable.toml"
DEV = "dev.toml"


class ReleaseError(ValueError):
    """The release cannot be made as the files and the tags stand.

    A plain ``ValueError``: the publish job runs this script without the package installed.
    """


def text_of(version: Version) -> str:
    return ".".join(str(part) for part in version)


def version_in(text: str, name: str) -> Version:
    """Return the ``version = "X.Y.Z"`` of a metadata file's text."""
    match = VERSION_LINE.search(text)
    if match is None:
        raise ReleaseError(f'{name} has no version = "X.Y.Z" line')
    return int(match.group(2)), int(match.group(3)), int(match.group(4))


def newest_release(tags: Iterable[str]) -> Version | None:
    """Return the highest ``vX.Y.Z`` among ``tags``, or ``None`` when there is none."""
    found = [TAG.match(tag.strip()) for tag in tags]
    versions = [(int(m.group(1)), int(m.group(2)), int(m.group(3))) for m in found if m]
    return max(versions, default=None)


def next_version(current: Version, released: Version | None) -> Version:
    """Return the version to publish for a file that says ``current``.

    A file whose ``MAJOR.MINOR`` was raised above the newest release keeps what it
    says. Without a release to compare with, the patch goes up as it always did.
    """
    if released is not None and current[:2] > released[:2]:
        return current
    return current[0], current[1], current[2] + 1


def write_version(path: Path, version: Version) -> None:
    text = path.read_text(encoding="utf-8")
    replaced = VERSION_LINE.sub(rf'\g<1>"{text_of(version)}"', text, count=1)
    path.write_text(replaced, encoding="utf-8")


def git_tags(root: Path) -> list[str]:
    """Return the release tags of the checkout at ``root``."""
    # A fixed argument list and no shell: nothing here comes from outside the workflow.
    result = subprocess.run(  # nosec B603 B607
        ["git", "tag", "--list", "v*"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_SECONDS,
        check=True,
    )
    return result.stdout.splitlines()


def bump(root: Path, released: Version | None) -> tuple[Version, Version]:
    """Write the release versions into both metadata files and return ``(stable, dev)``."""
    chosen: list[Version] = []
    for name in (STABLE, DEV):
        path = root / name
        version = next_version(version_in(path.read_text(encoding="utf-8"), name), released)
        chosen.append(version)
    stable, dev = chosen
    if released is not None and stable <= released:
        raise ReleaseError(
            f"{STABLE} would release {text_of(stable)}, which is not above the newest tag "
            f"v{text_of(released)}"
        )
    write_version(root / STABLE, stable)
    write_version(root / DEV, dev)
    return stable, dev


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if arguments != ["bump"]:
        sys.stderr.write("usage: stable_release.py bump\n")
        return 2
    root = Path.cwd()
    try:
        stable, dev = bump(root, newest_release(git_tags(root)))
    except ReleaseError as error:
        sys.stderr.write(f"{error}\n")
        return 1
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"new_version={text_of(stable)}\n")
            handle.write(f"dev_version={text_of(dev)}\n")
    sys.stdout.write(f"{STABLE} -> {text_of(stable)}\n{DEV}    -> {text_of(dev)}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
