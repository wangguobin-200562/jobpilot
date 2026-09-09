import pytest

from jobpilot.parsers import (
    EmptyFileError,
    FileTooLargeError,
    UnsupportedFileTypeError,
    parse_resume,
)
from jobpilot.parsers.resume_parser import MAX_RESUME_FILE_SIZE_BYTES
from jobpilot.parsers.text_cleaner import clean_resume_text


@pytest.mark.parametrize("filename", ["resume.txt", "resume.jpg", "resume.doc"])
def test_unsupported_file_type_is_rejected(filename: str) -> None:
    with pytest.raises(UnsupportedFileTypeError, match="Unsupported file type"):
        parse_resume(filename, b"content")


def test_empty_file_is_rejected() -> None:
    with pytest.raises(EmptyFileError, match="empty"):
        parse_resume("resume.pdf", b"")


def test_file_over_limit_is_rejected() -> None:
    oversized = b"x" * (MAX_RESUME_FILE_SIZE_BYTES + 1)

    with pytest.raises(FileTooLargeError, match="10 MB"):
        parse_resume("resume.pdf", oversized)


def test_text_cleaning_preserves_content_and_normalizes_whitespace() -> None:
    source = "  项目经历  \r\nPython / C++   \r\n\r\n\r\n• Built API  \r2024-2025  "

    cleaned = clean_resume_text(source)

    assert cleaned == "项目经历\nPython / C++\n\n• Built API\n2024-2025"
    assert "C++" in cleaned
    assert "2024-2025" in cleaned
