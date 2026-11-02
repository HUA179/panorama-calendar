"""Byte-level ICS serialization."""

from collections.abc import Iterable

from panorama_calendar.ics.folding import CRLF, fold_logical_line


def serialize_logical_lines(lines: Iterable[str]) -> bytes:
    """Fold every logical line and join with CRLF plus a final CRLF."""
    folded_lines = [fold_logical_line(line) for line in lines]
    if not folded_lines:
        raise ValueError("an ICS object requires at least one content line")
    return CRLF.join(folded_lines) + CRLF
