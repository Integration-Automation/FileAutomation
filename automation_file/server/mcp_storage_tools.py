"""The semantic tools that work on a directory: ``storage_list``, ``storage_copy`` and
``file_search``.

All three are bounded. A listing and a search return at most the policy's
``max_results`` entries and say when there were more. A content search reads at
most ``max_search_bytes`` in one call: a file that does not fit in what is left
of that budget is not opened at all and is reported under ``skipped``, so the
answer never claims a file was searched when only a part of it was.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from typing import Any

from automation_file.exceptions import FileAutomationException, StorageNotFoundException
from automation_file.server.mcp_file_tools import described, read_window, transfer
from automation_file.server.mcp_policy import MCPToolException, path_below
from automation_file.server.mcp_tool_model import (
    DRY_RUN_HELP,
    MAX_RESULTS_HELP,
    OVERWRITE_HELP,
    URI_HELP,
    SemanticTool,
    ToolSession,
    arguments_schema,
    flag,
    text,
    whole,
)
from automation_file.storage.storage import Storage
from automation_file.storage.tree import copy_tree
from automation_file.storage.types import FileInfo

FILE_SEARCH = "file_search"
STORAGE_LIST = "storage_list"
STORAGE_COPY = "storage_copy"
_MAX_PATTERN = 256
_MAX_NEEDLE = 1024
_SNIPPET = 200
_BINARY_PROBE = 8192
_ANY_NAME = "*"


def _files_below(directory: Storage, *, missing_ok: bool = False) -> dict[str, FileInfo]:
    """Return every file below ``directory`` by its relative path."""
    try:
        listing = directory.list_dir(recursive=True)
    except StorageNotFoundException:
        if missing_ok:
            return {}
        raise
    return {info.path: info for info in listing if not info.is_dir}


def storage_list(session: ToolSession, args: dict[str, Any]) -> dict[str, Any]:
    """List a directory; ``recursive`` adds every descendant."""
    directory = session.storage(args["uri"])
    listing = directory.list_dir(recursive=args["recursive"])
    limit = session.policy.clamp_results(args.get("max_results"))
    entries = [described(directory.uri.joinpath(info.path), info) for info in listing[:limit]]
    return {
        "uri": str(directory),
        "recursive": args["recursive"],
        "entries": entries,
        "count": len(entries),
        "total": len(listing),
        "truncated": len(listing) > limit,
    }


# ---------------------------------------------------------------------- storage_copy


def _copy_tree(session: ToolSession, args: dict[str, Any]) -> dict[str, Any]:
    """Copy every file below a directory, or plan that copy when ``dry_run`` is set."""
    source, target = session.storage(args["source"]), session.storage(args["target"])
    if (
        path_below(source.uri, target.uri) is not None
        or path_below(target.uri, source.uri) is not None
    ):
        raise MCPToolException(
            "storage_copy: the target is inside the source, or the source inside it"
        )
    files = _files_below(source)
    existing = _files_below(target, missing_ok=True)
    collisions = sorted(set(files) & set(existing))
    overwrite = bool(args["overwrite"])
    if overwrite and collisions:
        session.policy.require_overwrite(STORAGE_COPY)
    wanted = [path for path in sorted(files) if overwrite or path not in existing]
    limit = session.policy.max_results
    body: dict[str, Any] = {
        "kind": "tree",
        "source": str(source),
        "target": str(target),
        "dry_run": args["dry_run"],
        "planned": {
            "copy": len(wanted),
            "overwrite": len(collisions) if overwrite else 0,
            "skip": 0 if overwrite else len(collisions),
            "bytes": sum(files[path].size or 0 for path in wanted),
        },
        "paths": wanted[:limit],
        "existing": collisions[:limit],
        "truncated": len(wanted) > limit or len(collisions) > limit,
        "done": False,
    }
    if args["dry_run"]:
        return body
    result = copy_tree(source, target, overwrite=overwrite)
    errors = dict(list(result.errors.items())[:limit])
    body.update(
        done=True,
        ok=result.ok,
        copied=len(result.copied),
        skipped=len(result.skipped),
        failed=len(result.errors),
        errors=errors,
    )
    return body


def storage_copy(session: ToolSession, args: dict[str, Any]) -> dict[str, Any]:
    """Copy a file, or every file below a directory, to another location."""
    session.policy.require_write(STORAGE_COPY)
    if session.file(args["source"]).stat().is_dir:
        return _copy_tree(session, args)
    return {"kind": "file", **transfer(session, args, STORAGE_COPY)}


# ---------------------------------------------------------------------- file_search


@dataclass
class _Scan:
    """The budget of one content search and what it has used up."""

    budget: int
    needle: str
    case_sensitive: bool
    files: int = 0
    bytes_read: int = 0
    skipped: list[dict[str, str]] = field(default_factory=list)

    @property
    def remaining(self) -> int:
        return self.budget - self.bytes_read


def _folded(value: str, case_sensitive: bool) -> str:
    return value if case_sensitive else value.casefold()


def _name_matches(info: FileInfo, pattern: str, case_sensitive: bool) -> bool:
    """Match the name, or the whole relative path when the pattern holds a ``/``."""
    subject = info.path if "/" in pattern else info.name
    return fnmatch.fnmatchcase(_folded(subject, case_sensitive), _folded(pattern, case_sensitive))


def _first_hit(content: str, scan: _Scan) -> dict[str, Any] | None:
    """Return the first line of ``content`` that holds the needle, and how many lines do."""
    needle = _folded(scan.needle, scan.case_sensitive)
    first: tuple[int, str] | None = None
    lines = 0
    for number, line in enumerate(content.splitlines(), start=1):
        if needle in _folded(line, scan.case_sensitive):
            lines += 1
            first = first or (number, line)
    if first is None:
        return None
    return {"line": first[0], "snippet": first[1].strip()[:_SNIPPET], "matching_lines": lines}


def _searched(directory: Storage, info: FileInfo, scan: _Scan) -> dict[str, Any] | None:
    """Search one file. A file that cannot be searched goes to ``scan.skipped`` instead."""
    uri = str(directory.uri.joinpath(info.path))
    if info.size is None or info.size > scan.remaining:
        scan.skipped.append({"uri": uri, "reason": "larger than what is left of the read budget"})
        return None
    try:
        with directory.file(info.path).open_read() as stream:
            data = read_window(stream, 0, scan.remaining)
    except FileAutomationException as error:
        scan.skipped.append({"uri": uri, "reason": type(error).__name__})
        return None
    scan.files += 1
    scan.bytes_read += len(data)
    if b"\x00" in data[:_BINARY_PROBE]:
        scan.skipped.append({"uri": uri, "reason": "not a text file"})
        return None
    hit = _first_hit(data.decode("utf-8", errors="replace"), scan)
    return None if hit is None else {**described(uri, info), **hit}


def _content_matches(
    directory: Storage, candidates: list[FileInfo], scan: _Scan, limit: int
) -> tuple[list[dict[str, Any]], bool]:
    """Return the matching files and whether the search stopped at ``limit``."""
    matches: list[dict[str, Any]] = []
    for position, info in enumerate(candidates):
        if len(matches) >= limit:
            return matches, position < len(candidates)
        found = _searched(directory, info, scan)
        if found is not None:
            matches.append(found)
    return matches, False


def file_search(session: ToolSession, args: dict[str, Any]) -> dict[str, Any]:
    """Find files below a location by name pattern and, optionally, by a text they contain."""
    policy = session.policy
    directory = session.storage(args["uri"])
    pattern, needle = args["pattern"], args.get("content")
    case_sensitive = args["case_sensitive"]
    limit = policy.clamp_results(args.get("max_results"))
    candidates = [
        info
        for info in directory.list_dir(recursive=args["recursive"])
        if not info.is_dir and _name_matches(info, pattern, case_sensitive)
    ]
    body: dict[str, Any] = {
        "uri": str(directory),
        "pattern": pattern,
        "candidates": len(candidates),
    }
    if needle is None:
        matches = [
            described(directory.uri.joinpath(info.path), info) for info in candidates[:limit]
        ]
        body.update(matches=matches, count=len(matches), truncated=len(candidates) > limit)
        return body
    scan = _Scan(policy.max_search_bytes, needle, case_sensitive)
    matches, stopped = _content_matches(directory, candidates, scan, limit)
    body.update(
        matches=matches,
        count=len(matches),
        truncated=stopped,
        searched_files=scan.files,
        searched_bytes=scan.bytes_read,
        skipped=scan.skipped[:limit],
        skipped_count=len(scan.skipped),
        complete=not stopped and not scan.skipped,
    )
    return body


_COPY_ARGUMENTS = {
    "source": text(f"The file or directory to copy. {URI_HELP}", minLength=1),
    "target": text(
        f"Where the copy goes: a file for a file, a directory for a directory. {URI_HELP}",
        minLength=1,
    ),
    "overwrite": flag(
        f"{OVERWRITE_HELP} For a directory, files that exist at the target are skipped "
        "when this is false."
    ),
    "verify": flag("For a single file: compare the SHA-256 of both sides after the copy."),
    "dry_run": flag(DRY_RUN_HELP),
}

TOOLS: tuple[SemanticTool, ...] = (
    SemanticTool(
        FILE_SEARCH,
        "Find files below a directory by name pattern and, optionally, by a text they "
        "contain (a plain substring, not a regular expression). Results and the bytes "
        "read are capped: check 'truncated', and for a content search 'skipped' and "
        "'complete'.",
        arguments_schema(
            {
                "uri": text(f"The directory to search. {URI_HELP}", minLength=1),
                "pattern": text(
                    "Shell-style pattern for the file name: *.csv, report-2026-??.csv. With "
                    "a '/' it is matched against the path below the directory: 2026/*/*.csv. "
                    "Default: every file.",
                    default=_ANY_NAME,
                    minLength=1,
                    maxLength=_MAX_PATTERN,
                ),
                "content": text(
                    "Only return files that contain this text. The first matching line is "
                    "returned with its number.",
                    minLength=1,
                    maxLength=_MAX_NEEDLE,
                ),
                "recursive": flag("Search subdirectories too. Default true.", default=True),
                "case_sensitive": flag("Match names and content case-sensitively."),
                "max_results": whole(MAX_RESULTS_HELP),
            },
            required=("uri",),
        ),
        file_search,
    ),
    SemanticTool(
        STORAGE_LIST,
        "List the files and directories at a location in any storage backend, with size "
        "and modification time. Results are capped: check 'truncated' and 'total'.",
        arguments_schema(
            {
                "uri": text(f"The directory to list. {URI_HELP}", minLength=1),
                "recursive": flag("List every descendant, not only the direct children."),
                "max_results": whole(MAX_RESULTS_HELP),
            },
            required=("uri",),
        ),
        storage_list,
    ),
    SemanticTool(
        STORAGE_COPY,
        "Copy a file, or a whole directory tree, to another location, in the same storage "
        "backend or across two. Needs a server that allows writing. For a tree the result "
        "counts what was copied, skipped and failed; run it with dry_run=true first to see "
        "the plan.",
        arguments_schema(_COPY_ARGUMENTS, required=("source", "target")),
        storage_copy,
        changes=True,
    ),
)
