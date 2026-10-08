"""The semantic file tools: ``file_read``, ``file_write``, ``file_copy``, ``file_move``,
``file_checksum`` and ``file_verify``.

Each handler is a plain function ``(session, arguments) -> dict``. It reaches
storage only through ``session.file``, so every location is checked by the
policy's guard, and it asks the policy before it writes, replaces or deletes.
A handler that changes something returns its plan and stops there when
``dry_run`` is set.
"""

from __future__ import annotations

import base64
import binascii
import codecs
import hashlib
from dataclasses import dataclass
from typing import Any, BinaryIO

from automation_file.exceptions import (
    StorageAlreadyExistsException,
    StorageChecksumException,
    StorageNotFoundException,
    StoragePathTypeException,
)
from automation_file.server.mcp_policy import (
    LIMIT_EXCEEDED,
    MCPPermissionException,
    MCPToolException,
)
from automation_file.server.mcp_tool_model import (
    DRY_RUN_HELP,
    OVERWRITE_HELP,
    URI_HELP,
    SemanticTool,
    ToolSession,
    arguments_schema,
    flag,
    text,
    whole,
)
from automation_file.storage.backend import DEFAULT_CHECKSUM_ALGORITHM
from automation_file.storage.file import File
from automation_file.storage.types import Checksum, FileInfo

BASE64 = "base64"
FILE_READ = "file_read"
FILE_WRITE = "file_write"
FILE_COPY = "file_copy"
FILE_MOVE = "file_move"
FILE_CHECKSUM = "file_checksum"
FILE_VERIFY = "file_verify"
_UTF8 = "utf-8"
_CHUNK = 1024 * 1024
_ENCODING_HELP = (
    "A text encoding (utf-8, utf-16, big5, latin-1, ...) or base64 for content that is not text."
)


def described(uri: object, info: FileInfo) -> dict[str, Any]:
    """Return one file or directory the way the tools report it."""
    return {
        "uri": str(uri),
        "path": info.path,
        "name": info.name,
        "is_dir": info.is_dir,
        "size": info.size,
        "modified_at": info.modified_at.isoformat() if info.modified_at else None,
    }


def existing_file(source: File) -> FileInfo:
    """Return the ``FileInfo`` of ``source``, which must be a file that exists."""
    info = source.stat()
    if info.is_dir:
        raise StoragePathTypeException(f"{source} is a directory, not a file")
    return info


def replaceable(session: ToolSession, tool: str, target: File, overwrite: bool) -> FileInfo | None:
    """Return the file now at ``target`` (``None`` when there is none) if it may be replaced.

    An existing file needs both the caller's ``overwrite`` and the policy's
    permission to overwrite.
    """
    try:
        info = target.stat()
    except StorageNotFoundException:
        return None
    if info.is_dir:
        raise StoragePathTypeException(f"{target} is a directory, not a file")
    if not overwrite:
        hint = (
            "pass overwrite=true to replace it"
            if session.policy.allow_overwrite
            else "this server does not allow replacing files"
        )
        raise StorageAlreadyExistsException(f"{target} already exists; {hint}")
    session.policy.require_overwrite(tool)
    return info


def read_window(stream: BinaryIO, offset: int, limit: int) -> bytes:
    """Return at most ``limit`` bytes of ``stream``, starting ``offset`` bytes in."""
    if offset and stream.seekable():
        stream.seek(offset)
        offset = 0
    chunks: list[bytes] = []
    remaining = limit
    while offset > 0 or remaining > 0:
        chunk = stream.read(min(offset or remaining, _CHUNK))
        if not chunk:
            break
        if offset > 0:
            offset -= len(chunk)
        else:
            chunks.append(chunk)
            remaining -= len(chunk)
    return b"".join(chunks)


def _text_codec(encoding: str) -> str:
    try:
        "".encode(encoding)
    except LookupError as error:
        raise MCPToolException(
            f"unknown text encoding {encoding[:40]!r}; use utf-8, another text encoding, or base64"
        ) from error
    return encoding


def _decoded(data: bytes, encoding: str, complete: bool) -> tuple[str, int]:
    """Return ``data`` as text and the number of bytes that text stands for.

    When more of the file follows, a character cut in half at the end of ``data``
    is left for the next read.
    """
    decoder = codecs.getincrementaldecoder(_text_codec(encoding))()
    try:
        content = decoder.decode(data, final=complete)
    except UnicodeDecodeError as error:
        raise MCPToolException(
            f"the content is not {encoding} text from this offset; ask for encoding base64"
        ) from error
    return content, len(data) - len(decoder.getstate()[0])


def _encoded(content: str, encoding: str) -> bytes:
    if encoding == BASE64:
        try:
            return base64.b64decode(content, validate=True)
        except (binascii.Error, ValueError) as error:
            raise MCPToolException("content is not valid base64") from error
    try:
        return content.encode(_text_codec(encoding))
    except UnicodeEncodeError as error:
        raise MCPToolException(f"content cannot be written as {encoding}") from error


def file_read(session: ToolSession, args: dict[str, Any]) -> dict[str, Any]:
    """Return part of a file: at most ``max_bytes`` (and the policy's cap) from ``offset``."""
    source = session.file(args["uri"])
    info = existing_file(source)
    offset, encoding = args["offset"], args["encoding"]
    limit = min(args.get("max_bytes", session.policy.max_read_bytes), session.policy.max_read_bytes)
    with source.open_read() as stream:
        data = read_window(stream, offset, limit)
    complete = len(data) < limit if info.size is None else offset + len(data) >= info.size
    if encoding == BASE64:
        content, used = base64.b64encode(data).decode("ascii"), len(data)
    else:
        content, used = _decoded(data, encoding, complete)
    return {
        "uri": str(source),
        "size": info.size,
        "offset": offset,
        "bytes": used,
        "truncated": not complete,
        "next_offset": None if complete else offset + used,
        "encoding": encoding,
        "content": content,
    }


def file_write(session: ToolSession, args: dict[str, Any]) -> dict[str, Any]:
    """Store ``content`` as a file; the size is capped and an existing file needs overwrite."""
    policy = session.policy
    policy.require_write(FILE_WRITE)
    payload = _encoded(args["content"], args["encoding"])
    if len(payload) > policy.max_write_bytes:
        raise MCPPermissionException(
            f"the content is {len(payload)} bytes and this server writes at most "
            f"{policy.max_write_bytes} per call (--max-write-bytes)",
            LIMIT_EXCEEDED,
        )
    target = session.file(args["uri"])
    replaced = replaceable(session, FILE_WRITE, target, args["overwrite"])
    body: dict[str, Any] = {
        "uri": str(target),
        "size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "overwrites": replaced is not None,
        "replaced_size": None if replaced is None else replaced.size,
        "dry_run": args["dry_run"],
        "written": False,
    }
    if not args["dry_run"]:
        target.write(payload, overwrite=replaced is not None)
        body["written"] = True
    return body


@dataclass(frozen=True)
class _Transfer:
    """One copy or move that passed every check."""

    source: File
    target: File
    move: bool
    overwrite: bool
    verify: bool


def _carry_out(job: _Transfer) -> dict[str, Any]:
    """Copy or move the file; with ``verify`` the source is deleted only after the digests match."""
    if not job.verify:
        if job.move:
            job.source.move_to(job.target, overwrite=job.overwrite)
        else:
            job.source.copy_to(job.target, overwrite=job.overwrite)
        return {}
    expected = job.source.checksum()
    job.source.copy_to(job.target, overwrite=job.overwrite)
    actual = job.target.checksum()
    if not actual.matches(expected):
        raise StorageChecksumException(
            f"{job.target} does not have the SHA-256 of {job.source} after the copy; "
            "the source was left in place"
        )
    if job.move:
        job.source.delete()
    return {"sha256": actual.value, "verified": True}


def transfer(session: ToolSession, args: dict[str, Any], tool: str) -> dict[str, Any]:
    """Copy (or, for ``file_move``, move) one file after the policy's checks."""
    move = tool == FILE_MOVE
    if move:
        session.policy.require_delete(tool)
    else:
        session.policy.require_write(tool)
    source, target = session.file(args["source"]), session.file(args["target"])
    info = existing_file(source)
    if source.uri == target.uri:
        raise MCPToolException(f"{tool}: source and target are the same file")
    replaced = replaceable(session, tool, target, args["overwrite"])
    body: dict[str, Any] = {
        "source": str(source),
        "target": str(target),
        "size": info.size,
        "overwrites": replaced is not None,
        "replaced_size": None if replaced is None else replaced.size,
        "deletes_source": move,
        "dry_run": args["dry_run"],
        "done": False,
    }
    if not args["dry_run"]:
        job = _Transfer(source, target, move, replaced is not None, bool(args.get("verify")))
        body.update(_carry_out(job))
        body["done"] = True
    return body


def file_copy(session: ToolSession, args: dict[str, Any]) -> dict[str, Any]:
    """Copy one file to another location, in the same backend or another one."""
    return transfer(session, args, FILE_COPY)


def file_move(session: ToolSession, args: dict[str, Any]) -> dict[str, Any]:
    """Move one file: copy it, then delete the source."""
    return transfer(session, args, FILE_MOVE)


def file_checksum(session: ToolSession, args: dict[str, Any]) -> dict[str, Any]:
    """Return the digest of a file."""
    source = session.file(args["uri"])
    info = existing_file(source)
    digest = source.checksum(args["algorithm"])
    return {
        "uri": str(source),
        "size": info.size,
        "algorithm": digest.algorithm,
        "value": digest.value,
    }


def file_verify(session: ToolSession, args: dict[str, Any]) -> dict[str, Any]:
    """Compare the digest of a file with ``expected`` and say whether they match."""
    source = session.file(args["uri"])
    expected, algorithm = args["expected"].strip(), args["algorithm"]
    if ":" in expected:
        try:
            wanted = Checksum.parse(expected)
        except ValueError as error:
            raise MCPToolException(
                "file_verify: expected must be a hex digest or '<algorithm>:<hex digest>'"
            ) from error
        algorithm, expected = wanted.algorithm, wanted.value
    existing_file(source)
    actual = source.checksum(algorithm)
    return {
        "uri": str(source),
        "algorithm": actual.algorithm,
        "expected": expected.lower(),
        "actual": actual.value,
        "match": actual.matches(expected),
    }


_URI = {"uri": text(URI_HELP, minLength=1)}
_ALGORITHM = {
    "algorithm": text(
        "The hash: sha256 (default), sha512, sha1, md5 or another fixed-length hashlib name.",
        default=DEFAULT_CHECKSUM_ALGORITHM,
    )
}
_TRANSFER_ARGUMENTS = {
    "source": text(f"The file to read. {URI_HELP}", minLength=1),
    "target": text(f"The file to create. {URI_HELP}", minLength=1),
    "overwrite": flag(OVERWRITE_HELP),
    "verify": flag(
        "Compare the SHA-256 of the source and of the target after the copy and fail on a "
        "mismatch. A move then deletes the source only once the digests match."
    ),
    "dry_run": flag(DRY_RUN_HELP),
}

TOOLS: tuple[SemanticTool, ...] = (
    SemanticTool(
        FILE_READ,
        "Read a file from any storage backend. Returns the content as text, or as base64 "
        "for a file that is not text, with its size. The server caps the bytes returned: "
        "when 'truncated' is true, call again with offset set to 'next_offset'.",
        arguments_schema(
            {
                **_URI,
                "offset": whole("Byte to start at. Default 0.", minimum=0, default=0),
                "max_bytes": whole("Return at most this many bytes. The server caps it."),
                "encoding": text(_ENCODING_HELP, default=_UTF8, minLength=1),
            },
            required=("uri",),
        ),
        file_read,
    ),
    SemanticTool(
        FILE_WRITE,
        "Create a file from the given content. Needs a server that allows writing. Refuses "
        "to replace an existing file unless overwrite is true and the server allows "
        "overwriting. Returns the size and SHA-256 of what was written.",
        arguments_schema(
            {
                **_URI,
                "content": text("The whole content of the file. The server caps its size."),
                "encoding": text(_ENCODING_HELP, default=_UTF8, minLength=1),
                "overwrite": flag(OVERWRITE_HELP),
                "dry_run": flag(DRY_RUN_HELP),
            },
            required=("uri", "content"),
        ),
        file_write,
        changes=True,
    ),
    SemanticTool(
        FILE_COPY,
        "Copy one file to another location, in the same storage backend or across two "
        "(for example S3 to SFTP). The source stays. Needs a server that allows writing. "
        "Use storage_copy for a directory.",
        arguments_schema(_TRANSFER_ARGUMENTS, required=("source", "target")),
        file_copy,
        changes=True,
    ),
    SemanticTool(
        FILE_MOVE,
        "Move one file to another location, in the same storage backend or across two. "
        "The source is deleted, so the server must allow writing and deleting. Pass "
        "verify=true to delete the source only after the SHA-256 of the copy matches.",
        arguments_schema(_TRANSFER_ARGUMENTS, required=("source", "target")),
        file_move,
        changes=True,
    ),
    SemanticTool(
        FILE_CHECKSUM,
        "Compute the digest of a file (SHA-256 by default). Returns algorithm, value and size.",
        arguments_schema({**_URI, **_ALGORITHM}, required=("uri",)),
        file_checksum,
    ),
    SemanticTool(
        FILE_VERIFY,
        "Check that a file has an expected digest. Returns match (true or false) with the "
        "expected and the actual digest; a mismatch is a result, not an error.",
        arguments_schema(
            {
                **_URI,
                "expected": text(
                    "The digest to expect: hex, or '<algorithm>:<hex>' such as 'sha256:9f86...'.",
                    minLength=1,
                ),
                **_ALGORITHM,
            },
            required=("uri", "expected"),
        ),
        file_verify,
    ),
)
