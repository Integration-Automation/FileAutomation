"""Structured-data helpers: CSV, JSON Lines, YAML, Parquet.

All file I/O is UTF-8 and atomic where a destination file is written (temp
file + ``os.replace`` after success). YAML parsing uses ``yaml.safe_load`` —
never ``yaml.load`` — so a malicious config can't construct arbitrary Python
objects.

The functions in this module intentionally materialise results as Python
lists/dicts rather than iterators so they round-trip cleanly through the
JSON-based action payload protocol used by the executor, MCP bridge, and
TCP/HTTP servers. Callers that need streaming iteration can reach into the
underlying ``csv``/``pyarrow`` APIs directly.
"""

from __future__ import annotations

import csv
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from automation_file.exceptions import DataOpsException, FileNotExistsException
from automation_file.logging_config import file_automation_logger


def csv_filter(
    src: str,
    target: str,
    *,
    columns: list[str] | None = None,
    where_column: str | None = None,
    where_equals: str | None = None,
    delimiter: str = ",",
    encoding: str = "utf-8",
) -> int:
    """Copy ``src`` CSV rows into ``target``, optionally projecting and filtering.

    * ``columns`` — if given, the output keeps only these header names in
      this order. Unknown names raise :class:`DataOpsException`.
    * ``where_column`` + ``where_equals`` — keep only rows whose value in
      ``where_column`` exactly equals ``where_equals`` (string compare).
      Supplying one without the other raises.

    Returns the number of data rows written.
    """
    source = Path(src)
    if not source.is_file():
        raise FileNotExistsException(str(source))
    if (where_column is None) != (where_equals is None):
        raise DataOpsException("where_column and where_equals must be supplied together")
    dest = Path(target)
    dest.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    tmp_name: str | None = None
    try:
        with (
            open(source, encoding=encoding, newline="") as reader,
            tempfile.NamedTemporaryFile(
                mode="w",
                encoding=encoding,
                newline="",
                dir=str(dest.parent),
                delete=False,
                suffix=".tmp",
            ) as writer,
        ):
            tmp_name = writer.name
            parsed = csv.DictReader(reader, delimiter=delimiter)
            fieldnames = _resolve_fieldnames(parsed.fieldnames, columns)
            if where_column is not None and where_column not in (parsed.fieldnames or []):
                raise DataOpsException(f"where_column {where_column!r} is not in CSV header")
            output = csv.DictWriter(writer, fieldnames=fieldnames, delimiter=delimiter)
            output.writeheader()
            for row in parsed:
                if where_column is not None and row.get(where_column) != where_equals:
                    continue
                output.writerow({name: row.get(name, "") for name in fieldnames})
                written += 1
        os.replace(tmp_name, dest)
        tmp_name = None
    finally:
        if tmp_name is not None:
            Path(tmp_name).unlink(missing_ok=True)
    file_automation_logger.info("csv_filter: %s -> %s (%d rows)", source, dest, written)
    return written


def csv_to_jsonl(
    src: str,
    target: str,
    *,
    delimiter: str = ",",
    encoding: str = "utf-8",
) -> int:
    """Convert a CSV file to JSON Lines; return the number of records written."""
    source = Path(src)
    if not source.is_file():
        raise FileNotExistsException(str(source))
    dest = Path(target)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_name: str | None = None
    written = 0
    try:
        with (
            open(source, encoding=encoding, newline="") as reader,
            tempfile.NamedTemporaryFile(
                mode="w",
                encoding=encoding,
                dir=str(dest.parent),
                delete=False,
                suffix=".tmp",
            ) as writer,
        ):
            tmp_name = writer.name
            for row in csv.DictReader(reader, delimiter=delimiter):
                writer.write(json.dumps(row, ensure_ascii=False))
                writer.write("\n")
                written += 1
        os.replace(tmp_name, dest)
        tmp_name = None
    finally:
        if tmp_name is not None:
            Path(tmp_name).unlink(missing_ok=True)
    file_automation_logger.info("csv_to_jsonl: %s -> %s (%d records)", source, dest, written)
    return written


def jsonl_iter(
    path: str,
    *,
    limit: int | None = None,
    encoding: str = "utf-8",
) -> list[dict[str, Any]]:
    """Return every JSON Lines record in ``path`` as a list of dicts.

    ``limit`` caps the number of records returned (handy for previews on
    large files). Blank lines are skipped. Non-dict records are rejected so
    downstream consumers can count on a stable shape.
    """
    source = Path(path)
    if not source.is_file():
        raise FileNotExistsException(str(source))
    records: list[dict[str, Any]] = []
    with open(source, encoding=encoding) as reader:
        for line_no, raw in enumerate(reader, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as err:
                raise DataOpsException(f"{source}:{line_no} is not valid JSON: {err}") from err
            if not isinstance(record, dict):
                raise DataOpsException(
                    f"{source}:{line_no} is not a JSON object: {type(record).__name__}"
                )
            records.append(record)
            if limit is not None and len(records) >= limit:
                break
    return records


def jsonl_append(path: str, record: dict[str, Any], *, encoding: str = "utf-8") -> bool:
    """Append one JSON object as a new line in ``path``. Creates the file if absent."""
    if not isinstance(record, dict):
        raise DataOpsException(f"record must be a dict, got {type(record).__name__}")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False) + "\n"
    with open(target, "a", encoding=encoding) as writer:
        writer.write(line)
    return True


def _resolve_fieldnames(
    source_fields: list[str] | None,
    requested: list[str] | None,
) -> list[str]:
    if source_fields is None:
        raise DataOpsException("CSV has no header row")
    if requested is None:
        return list(source_fields)
    missing = [name for name in requested if name not in source_fields]
    if missing:
        raise DataOpsException(f"column(s) not in CSV header: {', '.join(missing)}")
    return list(requested)
