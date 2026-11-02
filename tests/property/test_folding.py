"""Property tests for UTF-8 octet folding."""

from hypothesis import given
from hypothesis import strategies as st

from panorama_calendar.ics.folding import CRLF, fold_logical_line, unfold_logical_line


@given(
    st.text(
        alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters="\r\n"),
        max_size=400,
    )
)
def test_fold_unfold_round_trip_and_line_width(value: str) -> None:
    """Any Unicode logical line must round-trip and respect 75 octets."""
    folded = fold_logical_line(value)
    assert unfold_logical_line(folded) == value.encode("utf-8")
    assert all(len(line) <= 75 for line in folded.split(CRLF))
    folded.decode("utf-8", errors="strict")
