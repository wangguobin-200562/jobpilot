"""Local document parsing adapters."""

from jobpilot.parsers.errors import (
    EmptyFileError,
    FileTooLargeError,
    NoReadableTextError,
    ResumeParseError,
    UnsupportedFileTypeError,
)
from jobpilot.parsers.resume_parser import parse_resume

__all__ = [
    "EmptyFileError",
    "FileTooLargeError",
    "NoReadableTextError",
    "ResumeParseError",
    "UnsupportedFileTypeError",
    "parse_resume",
]
