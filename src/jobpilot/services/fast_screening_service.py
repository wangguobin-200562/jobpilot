"""FLASH-only lightweight screening without final scores or personal data."""

from __future__ import annotations

from jobpilot.llm import LLMClient, ModelTier
from jobpilot.llm.structured_output import RequestTelemetry, generate_structured_output
from jobpilot.models import BatchJobInput, CandidateProfile
from jobpilot.models.fast_screening import CompactCandidateSummary, FastScreeningAssessment
from jobpilot.prompts.fast_screening import (
    FAST_SCREENING_SYSTEM_PROMPT,
    build_fast_screening_prompt,
)
from jobpilot.services.screening_preparation import (
    build_compact_candidate_summary,
    trim_job_description,
)


FAST_SCREENING_TEMPERATURE = 0.0
FAST_SCREENING_THINKING = False
FAST_SCREENING_MAX_TOKENS = 1200


def candidate_fast_screening_summary(candidate: CandidateProfile) -> dict:
    """Compatibility wrapper around the deterministic compact summary."""
    return build_compact_candidate_summary(candidate).model_dump(mode="json")


class FastScreeningService:
    MODEL_TIER = ModelTier.FLASH

    def __init__(self, client: LLMClient) -> None:
        self.client = client

    def assess(
        self,
        candidate: CandidateProfile,
        job_input: BatchJobInput,
        *,
        candidate_summary: CompactCandidateSummary | None = None,
        trimmed_jd: str | None = None,
        telemetry_callback: RequestTelemetry | None = None,
    ) -> FastScreeningAssessment:
        summary = candidate_summary or build_compact_candidate_summary(candidate)
        prompt = build_fast_screening_prompt(
            candidate_summary=summary.model_dump(mode="json"),
            job_title=job_input.job_title,
            jd_text=trimmed_jd if trimmed_jd is not None else trim_job_description(job_input.jd_text),
        )
        return generate_structured_output(
            self.client,
            system_prompt=FAST_SCREENING_SYSTEM_PROMPT,
            user_prompt=prompt,
            model_type=FastScreeningAssessment,
            model_tier=self.MODEL_TIER,
            temperature=FAST_SCREENING_TEMPERATURE,
            thinking=FAST_SCREENING_THINKING,
            repair_with_original_input=False,
            repair_constraints="Do not add numeric scores or new candidate/job facts.",
            repair_empty_response=False,
            telemetry_callback=telemetry_callback,
            max_tokens=FAST_SCREENING_MAX_TOKENS,
        )
