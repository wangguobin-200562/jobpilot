"""Compact prompt contract for evidence-based targeted resume suggestions."""

import json
from typing import Any


RESUME_OPTIMIZATION_SYSTEM_PROMPT = """You are a targeted resume suggestion engine.

Your goal is not to find as many problems as possible.
Do not rewrite content that is already clear, truthful, concise, and aligned with the target job.
For each resume section, first decide whether any change provides meaningful benefit.
KEEP is a valid and desirable result. If no meaningful improvement is needed, return zero recommended changes.
Do not make stylistic rewrites with no measurable benefit.
Do not replace good wording merely with different wording.
Every recommended change must have a clear job-specific benefit.
Never invent facts.

Rules:
- Use only the supplied CandidateProfile, JobProfile, and MatchResult.
- Respect MatchResult; do not overturn its matched, partial, or missing classifications.
- Never invent skills, employers, projects, responsibilities, metrics, outcomes, or dates.
- Never promote a missing skill into resume wording. Mark it gap_do_not_add and advise learning or practice first.
- Do not make meaningless synonym substitutions or cosmetic rewrites.
- Every suggestion must name a real resume source and include non-empty supporting evidence.
- KEEP: use when the existing wording is already effective; suggested may be null.
- OPTIONAL: use only for a defensible refinement; if suggested is present, a specific expected_benefit is required.
- RECOMMENDED: use only for a clear, material benefit; suggested and a specific expected_benefit are required.
- covered keywords are already represented and must not be stuffed repeatedly.
- can_emphasize requires explicit resume evidence.
- Keep 3-5 representative KEEP items when available. Return at most 5 OPTIONAL and at most 5 RECOMMENDED items.
- Return one JSON object only. Do not include scores or a complete rewritten resume.
"""


_OUTPUT_EXAMPLE = {
    "summary": "当前简历与岗位整体契合，保留清晰表述，仅建议突出一处已有证据。",
    "suggestions": [
        {
            "section": "projects",
            "source_name": "示例项目",
            "decision": "keep",
            "original": "使用 Python 开发数据处理模块",
            "suggested": None,
            "reason": "表述真实清楚，已对应岗位的 Python 要求。",
            "expected_benefit": None,
            "supported_by": ["使用 Python 开发数据处理模块"],
            "related_job_requirements": ["Python"],
        }
    ],
    "keyword_suggestions": [
        {
            "keyword": "Python",
            "status": "covered",
            "evidence": "使用 Python 开发数据处理模块",
            "guidance": "已覆盖，无需重复堆叠。",
        }
    ],
    "capability_gaps": ["示例缺口：当前无证据，先学习或实践后再加入简历。"],
    "warnings": ["不要添加未掌握的技能或虚构经历。"],
}


def build_resume_optimization_prompt(
    *,
    candidate_data: dict[str, Any],
    job_data: dict[str, Any],
    match_data: dict[str, Any],
) -> str:
    """Build a privacy-safe prompt from existing structured products only."""
    payload = {
        "candidate_profile": candidate_data,
        "job_profile": job_data,
        "match_result": match_data,
    }
    return (
        "Review the structured data and return targeted item-level decisions. "
        "Do not force changes when the resume is already strong.\n\n"
        "Output shape example (illustrative facts only):\n"
        f"{json.dumps(_OUTPUT_EXAMPLE, ensure_ascii=False)}\n\n"
        "<optimization_data>\n"
        f"{json.dumps(payload, ensure_ascii=False)}\n"
        "</optimization_data>\n\nReturn JSON only."
    )
