"""Conservative text cleanup for locally extracted resume content."""

import re


_EXCESS_BLANK_LINES = re.compile(r"\n{3,}")


def clean_resume_text(text: str) -> str:
    """Normalize whitespace while preserving resume wording and line structure."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = "\n".join(line.rstrip(" \t") for line in normalized.split("\n"))
    normalized = _EXCESS_BLANK_LINES.sub("\n\n", normalized)
    return normalized.strip()
