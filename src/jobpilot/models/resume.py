"""Data contracts for local resume parsing results."""

from typing import Literal

from pydantic import BaseModel, Field


class ParsedResume(BaseModel):
    """The text and basic metadata extracted from one resume file."""

    filename: str = Field(min_length=1)
    file_type: Literal["pdf", "docx"]
    file_size: int = Field(ge=1)
    text: str = Field(min_length=1)
    character_count: int = Field(ge=1)
    word_count: int = Field(ge=0)
    page_count: int | None = Field(default=None, ge=1)
