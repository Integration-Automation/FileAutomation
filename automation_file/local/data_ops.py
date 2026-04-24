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
from collections.abc import MutableMapping, MutableSequence, Sequence
from pathlib import Path
from typing import Any

from automation_file.exceptions import DataOpsException, FileNotExistsException
from automation_file.logging_config import file_automation_logger

_MISSING = object()


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
    written = _stream_csv_filter(
        source, dest, columns, where_column, where_equals, delimiter, encoding
    )
    file_automation_logger.info("csv_filter: %s -> %s (%d rows)", source, dest, written)
    return written


# pylint: disable-next=too-many-positional-arguments  # flat option bundle
def _stream_csv_filter(
    source: Path,
    dest: Path,
    columns: list[str] | None,
    where_column: str | None,
    where_equals: str | None,
    delimiter: str,
    encoding: str,
) -> int:
    """Do the actual streaming copy; separated so ``csv_filter`` stays simple."""
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
            written = _write_filtered_rows(
                reader, writer, columns, where_column, where_equals, delimiter
            )
        os.replace(tmp_name, dest)
        tmp_name = None
        return written
    finally:
        if tmp_name is not None:
            Path(tmp_name).unlink(missing_ok=True)


# pylint: disable-next=too-many-positional-arguments  # flat option bundle
def _write_filtered_rows(
    reader: Any,
    writer: Any,
    columns: list[str] | None,
    where_column: str | None,
    where_equals: str | None,
    delimiter: str,
) -> int:
    parsed = csv.DictReader(reader, delimiter=delimiter)
    fieldnames = _resolve_fieldnames(parsed.fieldnames, columns)
    if where_column is not None and where_column not in (parsed.fieldnames or []):
        raise DataOpsException(f"where_column {where_column!r} is not in CSV header")
    output = csv.DictWriter(writer, fieldnames=fieldnames, delimiter=delimiter)
    output.writeheader()
    written = 0
    for row in parsed:
        if where_column is not None and row.get(where_column) != where_equals:
            continue
        output.writerow({name: row.get(name, "") for name in fieldnames})
        written += 1
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
    source_fields: Sequence[str] | None,
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


def yaml_get(path: str, key_path: str, default: Any = None) -> Any:
    """Return the value at dotted ``key_path`` in a YAML file, or ``default``."""
    data = _yaml_load(path)
    result = _walk(data, _split_key(key_path))
    return default if result is _MISSING else result


def yaml_set(path: str, key_path: str, value: Any) -> bool:
    """Set the value at dotted ``key_path``. Creates intermediate dicts."""
    segments = _split_key(key_path)
    if not segments:
        raise DataOpsException("key_path must not be empty")
    data = _yaml_load(path)
    _set_in(data, segments, value)
    _yaml_dump(path, data)
    file_automation_logger.info("yaml_set: %s %s", path, key_path)
    return True


def yaml_delete(path: str, key_path: str) -> bool:
    """Delete the value at dotted ``key_path``; return True when a value was removed."""
    segments = _split_key(key_path)
    if not segments:
        raise DataOpsException("key_path must not be empty")
    data = _yaml_load(path)
    removed = _delete_in(data, segments)
    if removed:
        _yaml_dump(path, data)
        file_automation_logger.info("yaml_delete: %s %s", path, key_path)
    return removed


def parquet_read(
    path: str,
    *,
    limit: int | None = None,
    columns: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Read a Parquet file into a list of dicts.

    ``columns`` projects the output schema (unknown column names raise).
    ``limit`` caps the number of rows returned (reads the whole file but
    slices before conversion — handy for previews of multi-GB files).
    """
    import pyarrow.parquet as pq

    source = Path(path)
    if not source.is_file():
        raise FileNotExistsException(str(source))
    try:
        table = pq.read_table(str(source), columns=columns)
    except (OSError, ValueError) as err:
        raise DataOpsException(f"cannot read parquet {source}: {err}") from err
    if limit is not None:
        table = table.slice(0, limit)
    return table.to_pylist()


def parquet_write(path: str, records: list[dict[str, Any]]) -> int:
    """Write ``records`` (list of dicts) as a Parquet file; return the row count."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    if not isinstance(records, list):
        raise DataOpsException("records must be a list of dicts")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        table = pa.Table.from_pylist(records)
    except (TypeError, pa.ArrowInvalid) as err:
        raise DataOpsException(f"cannot build parquet table: {err}") from err
    tmp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=str(target.parent), delete=False, suffix=".tmp"
        ) as writer:
            tmp_name = writer.name
        pq.write_table(table, tmp_name)
        os.replace(tmp_name, target)
        tmp_name = None
    finally:
        if tmp_name is not None:
            Path(tmp_name).unlink(missing_ok=True)
    file_automation_logger.info("parquet_write: %s (%d rows)", target, table.num_rows)
    return table.num_rows


def csv_to_parquet(
    csv_path: str,
    parquet_path: str,
    *,
    delimiter: str = ",",
    encoding: str = "utf-8",
) -> int:
    """Convert a CSV file to Parquet; return the row count written."""
    source = Path(csv_path)
    if not source.is_file():
        raise FileNotExistsException(str(source))
    with open(source, encoding=encoding, newline="") as reader:
        rows = list(csv.DictReader(reader, delimiter=delimiter))
    return parquet_write(parquet_path, rows)


def _yaml_load(path: str) -> Any:
    import yaml

    source = Path(path)
    if not source.is_file():
        raise FileNotExistsException(str(source))
    try:
        return yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as err:
        raise DataOpsException(f"cannot parse YAML {source}: {err}") from err


def _yaml_dump(path: str, data: Any) -> None:
    import yaml

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(target.parent),
            delete=False,
            suffix=".tmp",
        ) as writer:
            tmp_name = writer.name
            yaml.safe_dump(data, writer, sort_keys=False, allow_unicode=True)
        os.replace(tmp_name, target)
        tmp_name = None
    finally:
        if tmp_name is not None:
            Path(tmp_name).unlink(missing_ok=True)


def _split_key(key_path: str) -> list[str]:
    if not isinstance(key_path, str):
        raise DataOpsException("key_path must be a string")
    return [seg for seg in key_path.split(".") if seg != ""]


def _walk(data: Any, segments: list[str]) -> Any:
    current: Any = data
    for segment in segments:
        try:
            current = _child(current, segment)
        except (KeyError, IndexError, TypeError):
            return _MISSING
    return current


def _child(container: Any, segment: str) -> Any:
    if isinstance(container, MutableMapping):
        return container[segment]
    if isinstance(container, MutableSequence) and _is_int_segment(segment):
        return container[int(segment)]
    raise TypeError(f"cannot index {type(container).__name__} by {segment!r}")


def _is_int_segment(segment: str) -> bool:
    return segment.lstrip("-").isdigit()


def _descend_for_set(container: Any, segment: str) -> Any:
    if isinstance(container, MutableMapping):
        if segment not in container or not isinstance(
            container[segment], (MutableMapping, MutableSequence)
        ):
            container[segment] = {}
        return container[segment]
    if isinstance(container, MutableSequence) and _is_int_segment(segment):
        return container[int(segment)]
    raise DataOpsException(f"cannot traverse into {segment!r}")


def _set_in(data: Any, segments: list[str], value: Any) -> None:
    container = data
    for segment in segments[:-1]:
        container = _descend_for_set(container, segment)
    last = segments[-1]
    if isinstance(container, MutableMapping):
        container[last] = value
        return
    if isinstance(container, MutableSequence) and _is_int_segment(last):
        _assign_into_sequence(container, last, value)
        return
    raise DataOpsException(f"cannot set into {type(container).__name__}")


def _assign_into_sequence(container: MutableSequence[Any], last: str, value: Any) -> None:
    idx = int(last)
    if -len(container) <= idx < len(container):
        container[idx] = value
        return
    if idx == len(container):
        container.append(value)
        return
    raise DataOpsException(f"list index out of range: {idx}")


def _delete_in(data: Any, segments: list[str]) -> bool:
    container = data
    for segment in segments[:-1]:
        try:
            container = _child(container, segment)
        except (KeyError, IndexError, TypeError):
            return False
    last = segments[-1]
    if isinstance(container, MutableMapping):
        if last not in container:
            return False
        del container[last]
        return True
    if isinstance(container, MutableSequence) and _is_int_segment(last):
        idx = int(last)
        if not -len(container) <= idx < len(container):
            return False
        del container[idx]
        return True
    return False
