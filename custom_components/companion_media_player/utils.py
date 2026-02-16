from typing import Any


def parse_int(value: Any) -> int | None:
    """Safely parse an integer from a value that might be str, int, or None."""
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None
