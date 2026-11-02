"""Byte-boundary examples for content-line folding."""

import pytest

from panorama_calendar.ics.folding import CRLF, fold_logical_line, unfold_logical_line


def test_ascii_75_octets_is_not_folded() -> None:
    """Exactly 75 octets fits on the first physical line."""
    assert fold_logical_line("a" * 75) == b"a" * 75


def test_ascii_76_octets_uses_continuation_space() -> None:
    """The continuation space is additional to the 74-byte payload."""
    folded = fold_logical_line("a" * 76)
    assert folded == b"a" * 75 + CRLF + b" a"


def test_chinese_never_splits_a_multibyte_codepoint() -> None:
    """Every physical line remains independently valid UTF-8."""
    original = "DESCRIPTION:" + "汉" * 100 + "🙂"
    folded = fold_logical_line(original)
    for line in folded.split(CRLF):
        assert len(line) <= 75
        line.decode("utf-8", errors="strict")
    assert unfold_logical_line(folded) == original.encode("utf-8")


def test_raw_line_breaks_are_rejected() -> None:
    """Raw newlines must be escaped before folding."""
    with pytest.raises(ValueError, match="cannot contain raw"):
        fold_logical_line("SUMMARY:first\nATTENDEE:injected")
