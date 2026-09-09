"""Deterministic parsing for separator-delimited batch job input."""

from __future__ import annotations

import re

from jobpilot.models import BatchJobInput
from jobpilot.services.job_analyzer import normalize_job_description


MIN_BATCH_JOBS = 1
MAX_BATCH_JOBS = 20
_SEPARATOR = re.compile(r"(?m)^\s*---\s*$")
_METADATA = re.compile(
    r"^\s*(公司|公司名称|岗位|岗位名称|职位|地点|工作地点|链接|岗位链接|source_url|JD|岗位描述)\s*[：:]\s*(.*)$",
    re.IGNORECASE,
)


class BatchInputError(ValueError):
    """Base error for locally invalid batch input."""


class BatchJobCountError(BatchInputError):
    """Raised when batch size is outside the supported range."""


class EmptyBatchJobError(BatchInputError):
    """Raised when a block contains metadata but no JD body."""


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _parse_block(index: int, block: str) -> BatchJobInput:
    metadata: dict[str, str | None] = {
        "company": None,
        "job_title": None,
        "location": None,
        "source_url": None,
    }
    jd_lines: list[str] = []
    reading_jd = False
    labels = {
        "公司": "company",
        "公司名称": "company",
        "岗位": "job_title",
        "岗位名称": "job_title",
        "职位": "job_title",
        "地点": "location",
        "工作地点": "location",
        "链接": "source_url",
        "岗位链接": "source_url",
        "source_url": "source_url",
    }

    for line in block.strip().splitlines():
        match = _METADATA.match(line)
        if not reading_jd and match:
            label, value = match.groups()
            if label.casefold() in {"jd", "岗位描述"}:
                reading_jd = True
                if value.strip():
                    jd_lines.append(value)
            else:
                metadata[labels[label.casefold()]] = _clean_optional(value)
            continue
        reading_jd = True
        jd_lines.append(line)

    jd_text = normalize_job_description("\n".join(jd_lines))
    if not jd_text:
        raise EmptyBatchJobError(f"第 {index} 个岗位缺少 JD 内容。")
    return BatchJobInput(
        index=index,
        company=metadata["company"],
        job_title=metadata["job_title"],
        location=metadata["location"],
        source_url=metadata["source_url"],
        jd_text=jd_text,
        raw_block=block.strip(),
    )


def parse_batch_job_input(raw_input: str) -> list[BatchJobInput]:
    """Split and parse 1–20 jobs without calling an AI model."""
    blocks = [block.strip() for block in _SEPARATOR.split(raw_input) if block.strip()]
    if len(blocks) < MIN_BATCH_JOBS:
        raise BatchJobCountError("批量筛选至少需要 2 个岗位；单个岗位请使用单岗位分析。")
    if len(blocks) > MAX_BATCH_JOBS:
        raise BatchJobCountError("一次最多分析 20 个岗位。")
    return [_parse_block(index, block) for index, block in enumerate(blocks, 1)]
