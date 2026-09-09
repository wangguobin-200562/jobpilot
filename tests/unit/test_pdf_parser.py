import pytest

from jobpilot.parsers import NoReadableTextError, ResumeParseError, parse_resume
from tests.fixtures.document_factory import make_pdf


def test_pdf_resume_is_parsed() -> None:
    result = parse_resume("resume.pdf", make_pdf("Jane Doe - Python Engineer"))

    assert result.file_type == "pdf"
    assert "Jane Doe" in result.text
    assert result.page_count == 1


def test_multi_page_pdf_extracts_every_page() -> None:
    result = parse_resume("resume.pdf", make_pdf("Page one", "Page two"))

    assert result.page_count == 2
    assert "Page one" in result.text
    assert "Page two" in result.text


def test_pdf_without_text_reports_ocr_limitation() -> None:
    with pytest.raises(NoReadableTextError, match="OCR is not supported"):
        parse_resume("scan.pdf", make_pdf(""))


def test_damaged_pdf_has_friendly_error() -> None:
    with pytest.raises(ResumeParseError, match="damaged or invalid"):
        parse_resume("broken.pdf", b"not a pdf")
