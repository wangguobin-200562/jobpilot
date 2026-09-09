"""In-memory DOCX text extraction, including table content."""

from io import BytesIO

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from jobpilot.parsers.errors import ResumeParseError


def _table_text(table: Table) -> list[str]:
    lines: list[str] = []
    for row in table.rows:
        cells: list[str] = []
        seen_cells: set[int] = set()
        for cell in row.cells:
            cell_id = id(cell._tc)
            if cell_id in seen_cells:
                continue
            seen_cells.add(cell_id)
            cells.append("\n".join(paragraph.text for paragraph in cell.paragraphs))
        lines.append("\t".join(cells))
    return lines


def extract_docx_text(file_bytes: bytes) -> str:
    """Extract paragraphs and top-level tables in document order."""
    try:
        document = Document(BytesIO(file_bytes))
        lines: list[str] = []
        for block in document.iter_inner_content():
            if isinstance(block, Paragraph):
                lines.append(block.text)
            elif isinstance(block, Table):
                lines.extend(_table_text(block))
        return "\n".join(lines)
    except Exception as exc:
        raise ResumeParseError(
            "Unable to read this DOCX file. The file may be damaged or invalid."
        ) from exc
