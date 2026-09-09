import pytest

from jobpilot.parsers import NoReadableTextError, ResumeParseError, parse_resume
from tests.fixtures.document_factory import make_docx


def test_docx_resume_reads_paragraphs() -> None:
    result = parse_resume(
        "resume.docx",
        make_docx(paragraphs=("Jane Doe", "Python Engineer")),
    )

    assert result.file_type == "docx"
    assert result.page_count is None
    assert "Jane Doe\nPython Engineer" in result.text


def test_docx_resume_reads_table_text() -> None:
    result = parse_resume(
        "resume.docx",
        make_docx(
            paragraphs=("Experience",),
            table_rows=(("Company", "Role"), ("Acme", "AI Intern")),
        ),
    )

    assert "Experience" in result.text
    assert "Company\tRole" in result.text
    assert "Acme\tAI Intern" in result.text


def test_empty_docx_has_friendly_error() -> None:
    with pytest.raises(NoReadableTextError, match="No readable text"):
        parse_resume("empty.docx", make_docx())


def test_damaged_docx_has_friendly_error() -> None:
    with pytest.raises(ResumeParseError, match="damaged or invalid"):
        parse_resume("broken.docx", b"not a docx")
