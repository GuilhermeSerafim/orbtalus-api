import logging
import unicodedata
from typing import Optional

ALLOWED_CONTROL_CHARS = {"\n", "\r", "\t"}
PREVIEW_LENGTH = 120


def _is_disallowed_control(char: str) -> bool:
    if char in ALLOWED_CONTROL_CHARS:
        return False

    return unicodedata.category(char).startswith("C")


def sanitize_text(
    value: Optional[str],
    *,
    field_name: str,
    logger: Optional[logging.Logger] = None,
    context: Optional[str] = None,
) -> Optional[str]:
    if value is None:
        return None

    sanitized = "".join(char for char in value if not _is_disallowed_control(char))

    if sanitized != value and logger is not None:
        location = f"{context}.{field_name}" if context else field_name
        logger.warning(
            "Sanitized control characters from %s (len=%d -> %d, preview=%s)",
            location,
            len(value),
            len(sanitized),
            repr(value[:PREVIEW_LENGTH]),
        )

    return sanitized
