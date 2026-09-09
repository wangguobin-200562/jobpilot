"""Dual-tier LLM provider boundary."""

from jobpilot.llm.client import DeepSeekLLMClient, LLMClient, ModelTier
from jobpilot.llm.errors import (
    EmptyCandidateProfileError,
    EmptyJobProfileError,
    LLMConfigurationError,
    LLMError,
    LLMRequestError,
    LLMRateLimitError,
    LLMTimeoutError,
    StructuredOutputError,
)

__all__ = [
    "DeepSeekLLMClient",
    "EmptyCandidateProfileError",
    "EmptyJobProfileError",
    "LLMClient",
    "LLMConfigurationError",
    "LLMError",
    "LLMRequestError",
    "LLMRateLimitError",
    "LLMTimeoutError",
    "ModelTier",
    "StructuredOutputError",
]
