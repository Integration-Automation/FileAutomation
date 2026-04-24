from __future__ import annotations

from pathlib import Path

import pytest

from automation_file import GrepException, build_default_registry, grep_files, iter_grep


@pytest.fixture(name="sample_tree")
def _sample_tree(tmp_path: Path) -> Path:
    (tmp_path / "a.txt").write_text("hello world\nfoo bar\nHELLO AGAIN\n", encoding="utf-8")
    (tmp_path / "b.log").write_text("nothing to see here\n", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "c.txt").write_text("another hello\n", encoding="utf-8")
    return tmp_path


def test_grep_literal_match(sample_tree: Path) -> None:
    hits = grep_files(str(sample_tree), "hello")
    paths = {hit["path"] for hit in hits}
    assert any(p.endswith("a.txt") for p in paths)
    assert any(p.endswith("c.txt") for p in paths)


def test_grep_case_insensitive(sample_tree: Path) -> None:
    hits = grep_files(str(sample_tree), "HELLO", ignore_case=True)
    assert len(hits) == 3


def test_grep_case_sensitive_by_default(sample_tree: Path) -> None:
    hits = grep_files(str(sample_tree), "HELLO")
    assert len(hits) == 1


def test_grep_regex(sample_tree: Path) -> None:
    hits = grep_files(str(sample_tree), r"fo+ bar", regex=True)
    assert len(hits) == 1


def test_grep_invalid_regex_raises(sample_tree: Path) -> None:
    with pytest.raises(GrepException):
        grep_files(str(sample_tree), "(", regex=True)


def test_grep_glob_filter(sample_tree: Path) -> None:
    hits = grep_files(str(sample_tree), "hello", glob="*.log")
    assert not hits


def test_grep_empty_pattern_raises(sample_tree: Path) -> None:
    with pytest.raises(GrepException):
        grep_files(str(sample_tree), "")


def test_grep_nonexistent_root(tmp_path: Path) -> None:
    with pytest.raises(GrepException):
        grep_files(str(tmp_path / "nope"), "anything")


def test_grep_max_matches(sample_tree: Path) -> None:
    hits = grep_files(str(sample_tree), "hello", ignore_case=True, max_matches=2)
    assert len(hits) == 2


def test_grep_reports_line_numbers(sample_tree: Path) -> None:
    hits = grep_files(str(sample_tree), "bar")
    assert hits[0]["line"] == 2


def test_iter_grep_streams(sample_tree: Path) -> None:
    found = 0
    for _hit in iter_grep(str(sample_tree), "hello", ignore_case=True):
        found += 1
        if found >= 2:
            break
    assert found == 2


def test_grep_registered() -> None:
    registry = build_default_registry()
    assert "FA_grep" in registry


def test_grep_long_line_truncated(tmp_path: Path) -> None:
    (tmp_path / "big.txt").write_text("x" * 10000 + " needle\n", encoding="utf-8")
    hits = grep_files(str(tmp_path), "needle", max_line_len=100)
    assert "…" in str(hits[0]["text"])


def test_grep_binary_safe(tmp_path: Path) -> None:
    (tmp_path / "bin.dat").write_bytes(b"\x00\x01\x02needle\x00")
    (tmp_path / "txt.txt").write_text("needle here\n", encoding="utf-8")
    hits = grep_files(str(tmp_path), "needle")
    assert len(hits) >= 1
