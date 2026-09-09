"""Safe, user-facing errors for the LLM boundary."""


class LLMError(RuntimeError):
    """Base error for configured model operations."""


class LLMConfigurationError(LLMError):
    """Raised before any request when required configuration is missing."""


class LLMRequestError(LLMError):
    """Raised when the provider request fails."""


class LLMTimeoutError(LLMRequestError):
    """Raised when the provider does not respond before the timeout."""


class LLMRateLimitError(LLMRequestError):
    """Raised when the provider asks the caller to reduce request pressure."""


class StructuredOutputError(LLMError):
    """Raised when model output cannot be validated after one repair."""


class EmptyCandidateProfileError(StructuredOutputError):
    """Raised when a valid response contains no core resume information."""


class EmptyJobProfileError(StructuredOutputError):
    """Raised when a valid response contains no core job information."""
