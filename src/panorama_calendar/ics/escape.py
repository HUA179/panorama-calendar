"""RFC 5545 TEXT escaping."""


def escape_text(value: str) -> str:
    """Escape a TEXT value and neutralize raw line-break injection."""
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    return (
        normalized.replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace(";", "\\;")
        .replace(",", "\\,")
    )


def unescape_text(value: str) -> str:
    """Reverse TEXT escaping for round-trip tests."""
    output: list[str] = []
    index = 0
    escapes = {"n": "\n", "N": "\n", "\\": "\\", ";": ";", ",": ","}
    while index < len(value):
        if value[index] == "\\":
            if index + 1 >= len(value):
                raise ValueError("dangling escape at end of TEXT value")
            next_character = value[index + 1]
            output.append(escapes.get(next_character, next_character))
            index += 2
        else:
            output.append(value[index])
            index += 1
    return "".join(output)
