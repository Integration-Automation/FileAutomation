"""Tests for automation_file.local.text_ops."""

from __future__ import annotations

from pathlib import Path

import pytest

from automation_file import (
    TextOpsException,
    build_default_registry,
    encoding_convert,
    file_merge,
    file_split,
    line_count,
    sed_replace,
)
from automation_file.exceptions import FileNotExistsException


def test_file_split_produces_ordered_parts(tmp_path: Path) -> None:
    source = tmp_path / "payload.bin"
    source.write_bytes(b"0123456789abcdef")
    parts = file_split(str(source), chunk_size=5)
    assert [Path(p).name for p in parts] == [
        "payload.bin.part000",
        "payload.bin.part001",
        "payload.bin.part002",
        "payload.bin.part003",
    ]
    assert Path(parts[0]).read_bytes() == b"01234"
    assert Path(parts[-1]).read_bytes() == b"f"


def test_file_split_respects_output_dir(tmp_path: Path) -> None:
    source = tmp_path / "a.txt"
    source.write_bytes(b"hello world")
    dest = tmp_path / "parts"
    parts = file_split(str(source), chunk_size=4, output_dir=str(dest))
    assert all(Path(p).parent == dest for p in parts)


def test_file_split_rejects_non_positive_chunk(tmp_path: Path) -> None:
    source = tmp_path / "empty.bin"
    source.write_bytes(b"x")
    with pytest.raises(TextOpsException):
        file_split(str(source), chunk_size=0)


def test_file_split_rejects_missing_source(tmp_path: Path) -> None:
    with pytest.raises(FileNotExistsException):
        file_split(str(tmp_path / "missing"), chunk_size=10)


def test_file_merge_roundtrip(tmp_path: Path) -> None:
    source = tmp_path / "big.bin"
    source.write_bytes(b"abcdefghijklmno")
    parts = file_split(str(source), chunk_size=3)
    merged = tmp_path / "rebuilt.bin"
    assert file_merge(parts, str(merged)) is True
    assert merged.read_bytes() == source.read_bytes()


def test_file_merge_rejects_missing_part(tmp_path: Path) -> None:
    with pytest.raises(FileNotExistsException):
        file_merge([str(tmp_path / "gone.part000")], str(tmp_path / "out"))


def test_file_merge_rejects_empty_parts(tmp_path: Path) -> None:
    with pytest.raises(TextOpsException):
        file_merge([], str(tmp_path / "out"))


def test_encoding_convert_utf8_to_latin1(tmp_path: Path) -> None:
    source = tmp_path / "a.txt"
    source.write_text("café", encoding="utf-8")
    target = tmp_path / "b.txt"
    encoding_convert(str(source), str(target), "utf-8", "latin-1")
    assert target.read_text(encoding="latin-1") == "café"


def test_encoding_convert_reports_bad_mapping(tmp_path: Path) -> None:
    source = tmp_path / "a.txt"
    source.write_text("hello", encoding="utf-8")
    target = tmp_path / "b.txt"
    with pytest.raises(TextOpsException):
        encoding_convert(str(source), str(target), "not-a-real-codec", "utf-8")


def test_line_count_counts_newlines(tmp_path: Path) -> None:
    source = tmp_path / "lines.txt"
    source.write_text("one\ntwo\nthree\n", encoding="utf-8")
    assert line_count(str(source)) == 3


def test_line_count_handles_no_trailing_newline(tmp_path: Path) -> None:
    source = tmp_path / "lines.txt"
    source.write_text("one\ntwo", encoding="utf-8")
    assert line_count(str(source)) == 2


def test_sed_replace_literal(tmp_path: Path) -> None:
    source = tmp_path / "t.txt"
    source.write_text("aaa bbb aaa", encoding="utf-8")
    assert sed_replace(str(source), "aaa", "XXX") == 2
    assert source.read_text(encoding="utf-8") == "XXX bbb XXX"


def test_sed_replace_regex_with_backref(tmp_path: Path) -> None:
    source = tmp_path / "t.txt"
    source.write_text("hello world", encoding="utf-8")
    assert sed_replace(str(source), r"(\w+) (\w+)", r"\2 \1", regex=True) == 1
    assert source.read_text(encoding="utf-8") == "world hello"


def test_sed_replace_respects_count(tmp_path: Path) -> None:
    source = tmp_path / "t.txt"
    source.write_text("a a a a", encoding="utf-8")
    assert sed_replace(str(source), "a", "b", count=2) == 2
    assert source.read_text(encoding="utf-8") == "b b a a"


def test_sed_replace_rejects_empty_literal_pattern(tmp_path: Path) -> None:
    source = tmp_path / "t.txt"
    source.write_text("abc", encoding="utf-8")
    with pytest.raises(TextOpsException):
        sed_replace(str(source), "", "x")


def test_sed_replace_rejects_bad_regex(tmp_path: Path) -> None:
    source = tmp_path / "t.txt"
    source.write_text("abc", encoding="utf-8")
    with pytest.raises(TextOpsException):
        sed_replace(str(source), "[unclosed", "x", regex=True)


def test_text_ops_registered() -> None:
    registry = build_default_registry()
    for name in (
        "FA_file_split",
        "FA_file_merge",
        "FA_encoding_convert",
        "FA_line_count",
        "FA_sed_replace",
    ):
        assert name in registry
