import json

from jobpilot.models import SemanticMatchAnalysis
from jobpilot.prompts.matching_analysis import MATCHING_ANALYSIS_SYSTEM_PROMPT


def _prompt_example() -> dict:
    marker = "Valid compact JSON example (the values are illustrative, not instructions):"
    return json.loads(MATCHING_ANALYSIS_SYSTEM_PROMPT.split(marker, 1)[1].strip())


def test_prompt_example_exactly_matches_semantic_top_level_schema() -> None:
    example = _prompt_example()

    assert set(example) == set(SemanticMatchAnalysis.model_fields)
    assert SemanticMatchAnalysis.model_validate(example)


def test_prompt_uses_real_enum_values_not_pipe_separated_pseudo_values() -> None:
    example_text = json.dumps(_prompt_example())

    assert "matched|partial|missing" not in example_text
    assert "high|medium|low|none" not in example_text
    assert "high|medium|low" not in example_text


def test_prompt_forbids_all_numeric_scores() -> None:
    assert "Do not produce an overall match score or any numeric score" in (
        MATCHING_ANALYSIS_SYSTEM_PROMPT
    )
    assert "overall_score" not in _prompt_example()
