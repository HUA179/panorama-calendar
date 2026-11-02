"""UTF-8 octet-based content-line folding."""

CRLF = b"\r\n"


def _utf8_codepoint_size(first_byte: int) -> int:
    """Return encoded codepoint length from its leading byte."""
    if first_byte <= 0x7F:
        return 1
    if 0xC2 <= first_byte <= 0xDF:
        return 2
    if 0xE0 <= first_byte <= 0xEF:
        return 3
    if 0xF0 <= first_byte <= 0xF4:
        return 4
    raise ValueError(f"invalid UTF-8 leading byte: {first_byte:#x}")


def fold_logical_line(line: str) -> bytes:
    """Fold at 75 octets by walking UTF-8 bytes without splitting codepoints.

    Continuation lines have a one-byte leading space, leaving 74 octets for
    their payload. Raw CR/LF is rejected because TEXT must be escaped first.
    """
    if "\r" in line or "\n" in line:
        raise ValueError("logical content lines cannot contain raw CR or LF")

    encoded = line.encode("utf-8")
    chunks: list[bytes] = []
    current = bytearray()
    payload_limit = 75
    index = 0

    while index < len(encoded):
        codepoint_size = _utf8_codepoint_size(encoded[index])
        if len(current) + codepoint_size > payload_limit:
            chunks.append(bytes(current))
            current = bytearray()
            payload_limit = 74
        current.extend(encoded[index : index + codepoint_size])
        index += codepoint_size

    chunks.append(bytes(current))
    output = bytearray(chunks[0])
    for chunk in chunks[1:]:
        output.extend(CRLF)
        output.extend(b" ")
        output.extend(chunk)
    return bytes(output)


def unfold_logical_line(folded: bytes) -> bytes:
    """Remove RFC 5545 folding from one logical line."""
    return folded.replace(CRLF + b" ", b"").replace(CRLF + b"\t", b"")
