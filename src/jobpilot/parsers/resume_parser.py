"""Validation and unified entry point for local resume parsing."""

from pathlib import Path
import re

from jobpilot.models import ParsedResume
from jobpilot.parsers.docx_parser import extract_docx_text
from jobpilot.parsers.errors import (
    EmptyFileError,
    FileTooLargeError,
    NoReadableTextError,
    ResumeParseError,
    UnsupportedFileTypeError,
)
from jobpilot.parsers.pdf_parser import extract_pdf_text
from jobpilot.parsers.text_cleaner import clean_resume_text


MAX_RESUME_FILE_SIZE_MB = 10
MAX_RESUME_FILE_SIZE_BYTES = MAX_RESUME_FILE_SIZE_MB * 1024 * 1024
SUPPORTED_RESUME_TYPES = {".pdf", ".docx"}
_WORD_PATTERN = re.compile(r"[\u3400-\u9fff]+|[A-Za-z0-9][\w.+#/-]*")


def _count_words(text: str) -> int:
    return len(_WORD_PATTERN.findall(text))


def parse_resume(filename: str, file_bytes: bytes) -> ParsedResume:
    """Validate, parse, and clean a PDF or DOCX resume from memory."""
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_RESUME_TYPES:
        raise UnsupportedFileTypeError(
            "Unsupported file type. Supported formats: PDF, DOCX."
        )
    if not file_bytes:
        raise EmptyFileError("The uploaded file is empty.")
    if len(file_bytes) > MAX_RESUME_FILE_SIZE_BYTES:
        raise FileTooLargeError(
            f"The uploaded file exceeds the {MAX_RESUME_FILE_SIZE_MB} MB limit."
        )

    page_count: int | None = None
    try:
        if suffix == ".pdf":
            raw_text, page_count = extract_pdf_text(file_bytes)
        else:
            raw_text = extract_docx_text(file_bytes)
    except ResumeParseError:
        raise
    except Exception as exc:
        raise ResumeParseError("The resume could not be parsed.") from exc

    text = clean_resume_text(raw_text)
    if not text:
        if suffix == ".pdf":
            raise NoReadableTextError(
                "No readable text was found in this PDF. "
                "Scanned-image PDF OCR is not supported yet."
            )
        raise NoReadableTextError("No readable text was found in this DOCX file.")

    return ParsedResume(
        filename=filename,
        file_type=suffix.removeprefix("."),
        file_size=len(file_bytes),
        text=text,
        character_count=len(text),
        word_count=_count_words(text),
        page_count=page_count,
    )
