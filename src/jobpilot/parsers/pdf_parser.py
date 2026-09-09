"""In-memory PDF text extraction."""

import pymupdf

from jobpilot.parsers.errors import ResumeParseError


def extract_pdf_text(file_bytes: bytes) -> tuple[str, int]:
    """Extract page text and page count from an in-memory PDF."""
    document: pymupdf.Document | None = None
    try:
        document = pymupdf.open(stream=file_bytes, filetype="pdf")
        if document.needs_pass:
            raise ResumeParseError(
                "This PDF is encrypted and cannot be read without a password."
            )

        page_count = document.page_count
        page_text = [page.get_text("text") for page in document]
        return "\n".join(page_text), page_count
    except ResumeParseError:
        raise
    except Exception as exc:
        raise ResumeParseError(
            "Unable to read this PDF. The file may be damaged or invalid."
        ) from exc
    finally:
        if document is not None:
            document.close()
