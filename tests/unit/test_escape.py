"""TEXT escaping tests."""

from panorama_calendar.ics.escape import escape_text, unescape_text


def test_text_escape_round_trip() -> None:
    """Backslashes, separators and newlines survive a round trip."""
    original = "one,two;three\\four\r\nfive\rsix\nseven"
    escaped = escape_text(original)
    assert "\r" not in escaped
    assert "\n" not in escaped
    assert unescape_text(escaped) == "one,two;three\\four\nfive\nsix\nseven"


def test_text_escape_prevents_property_injection() -> None:
    """Injected source text cannot create a new ICS property."""
    escaped = escape_text("hello\nBEGIN:VALARM")
    assert escaped == "hello\\nBEGIN:VALARM"
