"""Provider-neutral JSON normalization, validation, and one-shot repair."""

import json
import logging
import re
from collections.abc import Callable
from time import perf_counter
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from jobpilot.llm.client import LLMClient, ModelTier
from jobpilot.llm.errors import StructuredOutputError


logger = logging.getLogger(__name__)
ModelT = TypeVar("ModelT", bound=BaseModel)
RequestTelemetry = Callable[[ModelTier, str, float, float], None]
STRUCTURED_OUTPUT_MESSAGE = (
    "The AI response could not be converted into a valid candidate profile. "
    "Please try again."
)
_CODE_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)


def _json_candidate(response_text: str) -> str:
    text = response_text.strip()
    if not text:
        raise StructuredOutputError(STRUCTURED_OUTPUT_MESSAGE)

    fence = _CODE_FENCE.search(text)
    if fence:
        text = fence.group(1).strip()

    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise StructuredOutputError(STRUCTURED_OUTPUT_MESSAGE)
    return text[start : end + 1]


def parse_structured_output(response_text: str, model_type: type[ModelT]) -> ModelT:
    """Normalize untrusted model text and validate it with Pydantic."""
    payload: Any = None
    try:
        payload = json.loads(_json_candidate(response_text))
        result = model_type.model_validate(payload)
        logger.info(
            "Structured output validated: model_type=%s",
            model_type.__name__,
        )
        return result
    except StructuredOutputError:
        logger.warning(
            "Structured output validation summary: model_type=%s "
            "response_content_length=%d top_level_keys=[] "
            "validation_error_type=%s validation_error_field_names=[] "
            "unexpected_field_names=[] missing_field_names=[]",
            model_type.__name__,
            len(response_text),
            "empty_response" if not response_text.strip() else "json_object_not_found",
        )
        raise
    except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
        top_level_keys = sorted(payload) if isinstance(payload, dict) else []
        expected_fields = set(model_type.model_fields)
        unexpected_fields = (
            sorted(set(payload) - expected_fields) if isinstance(payload, dict) else []
        )
        missing_fields = (
            sorted(
                name
                for name, field in model_type.model_fields.items()
                if field.is_required() and name not in payload
            )
            if isinstance(payload, dict)
            else []
        )
        validation_fields: list[str] = []
        validation_types: list[str] = []
        if isinstance(exc, ValidationError):
            for error in exc.errors(include_url=False, include_context=False, include_input=False):
                location = ".".join(str(part) for part in error["loc"])
                if location:
                    validation_fields.append(location)
                validation_types.append(error["type"])
        else:
            validation_types.append(type(exc).__name__)
        logger.warning(
            "Structured output validation summary: model_type=%s "
            "response_content_length=%d top_level_keys=%s "
            "validation_error_type=%s validation_error_field_names=%s "
            "unexpected_field_names=%s missing_field_names=%s",
            model_type.__name__,
            len(response_text),
            top_level_keys,
            sorted(set(validation_types)),
            sorted(set(validation_fields)),
            unexpected_fields,
            missing_fields,
        )
        raise StructuredOutputError(STRUCTURED_OUTPUT_MESSAGE) from exc


def generate_structured_output(
    client: LLMClient,
    *,
    system_prompt: str,
    user_prompt: str,
    model_type: type[ModelT],
    model_tier: ModelTier,
    temperature: float | None = None,
    thinking: bool | None = None,
    repair_with_original_input: bool = True,
    repair_constraints: str | None = None,
    repair_empty_response: bool = True,
    telemetry_callback: RequestTelemetry | None = None,
    max_tokens: int | None = None,
) -> ModelT:
    """Generate and validate JSON, allowing exactly one Flash repair attempt."""
    primary_started = perf_counter()
    response = client.generate(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model_tier=model_tier,
        json_mode=True,
        temperature=temperature,
        thinking=thinking,
        max_tokens=max_tokens,
    )
    if telemetry_callback:
        telemetry_callback(model_tier, "primary", primary_started, perf_counter())
    try:
        return parse_structured_output(response, model_type)
    except StructuredOutputError:
        if not response.strip() and not repair_empty_response:
            logger.warning(
                "Structured output repair skipped tier=%s reason=empty_source_response",
                model_tier.name,
            )
            raise
        logger.warning(
            "Structured output validation failed tier=%s; retrying repair with FLASH",
            model_tier.name,
        )

    repair_parts = [
        "Convert the following invalid response into JSON that matches this schema. "
        "Repair only JSON syntax, field names, field types, and allowed enum values. "
        "Preserve only facts and judgments already present in the invalid response. "
        "Do not add, infer, or redo the original task.",
        f"JSON schema:\n{json.dumps(model_type.model_json_schema(), ensure_ascii=False)}",
    ]
    if repair_constraints:
        repair_parts.append(f"Repair constraints:\n{repair_constraints}")
    if repair_with_original_input:
        repair_parts.append(f"Original task input:\n{user_prompt}")
    repair_parts.append(f"Invalid response:\n{response}")
    repair_prompt = "\n\n".join(repair_parts)
    repair_started = perf_counter()
    repaired = client.generate(
        system_prompt="Repair JSON only. Return one JSON object and no explanation.",
        user_prompt=repair_prompt,
        model_tier=ModelTier.FLASH,
        json_mode=True,
        temperature=temperature,
        thinking=thinking,
        max_tokens=max_tokens,
    )
    if telemetry_callback:
        telemetry_callback(ModelTier.FLASH, "repair", repair_started, perf_counter())
    try:
        return parse_structured_output(repaired, model_type)
    except StructuredOutputError as exc:
        logger.warning("Structured output repair failed tier=FLASH")
        raise StructuredOutputError(STRUCTURED_OUTPUT_MESSAGE) from exc
