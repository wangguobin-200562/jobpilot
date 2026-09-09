"""User-facing exceptions raised by resume parsers."""


class ResumeParseError(ValueError):
    """Base error for resume validation and parsing failures."""


class UnsupportedFileTypeError(ResumeParseError):
    """Raised when a resume does not use a supported file extension."""


class FileTooLargeError(ResumeParseError):
    """Raised when a resume exceeds the configured upload limit."""


class EmptyFileError(ResumeParseError):
    """Raised when an uploaded file contains no bytes."""


class NoReadableTextError(ResumeParseError):
    """Raised when a valid document contains no extractable text."""
