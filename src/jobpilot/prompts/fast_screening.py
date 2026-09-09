"""Compact prompt for FLASH resume-to-JD triage."""

import json


FAST_SCREENING_SYSTEM_PROMPT = """You are a conservative resume-to-job screening engine.
Extract only the core required skills and obvious hard requirements, then decide whether
the job is relevant enough for deeper analysis. Do not invent facts. Minor tool gaps must
not make an otherwise relevant job low relevance. Return one JSON object only. Never
return a numeric score or hiring probability. The reason field must be concise,
natural Simplified Chinese even when the resume or job text contains English terms."""


def build_fast_screening_prompt(
    *, candidate_summary: dict, job_title: str | None, jd_text: str
) -> str:
    """Keep PII out and send only evidence needed for triage."""
    shape = {
        "job_title": None,
        "core_required_skills": [],
        "matched_core_skills": [],
        "missing_core_skills": [],
        "hard_requirement_risks": [],
        "relevance": "high | medium | low | none",
        "decision_confidence": "high | medium | low",
        "reason": "一条自然、简洁、有证据的中文说明，最多 160 字",
    }
    return (
        "Decide whether this job needs deeper matching. Extract no more than five "
        "items in each list. Treat requirements independently.\n\n"
        f"Candidate evidence (contains no name, phone, or email):\n"
        f"{json.dumps(candidate_summary, ensure_ascii=False)}\n\n"
        f"Explicit job title:\n{job_title or 'unknown'}\n\n"
        f"Job description:\n<job_description>\n{jd_text}\n</job_description>\n\n"
        f"Required JSON shape:\n{json.dumps(shape, ensure_ascii=False)}"
    )
