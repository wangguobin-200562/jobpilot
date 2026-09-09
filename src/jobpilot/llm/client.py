"""Small dual-tier OpenAI-compatible client for DeepSeek."""

from enum import Enum
import logging
import threading
from typing import Any, Protocol

from openai import APITimeoutError, OpenAI, OpenAIError, RateLimitError

from jobpilot.config import AppConfig, load_config
from jobpilot.llm.errors import (
    LLMConfigurationError,
    LLMRequestError,
    LLMRateLimitError,
    LLMTimeoutError,
)


logger = logging.getLogger(__name__)
DEFAULT_LLM_TIMEOUT_SECONDS = 60.0
DEFAULT_MAX_OUTPUT_TOKENS = 8192


class ModelTier(str, Enum):
    FLASH = "flash"
    PRO = "pro"


class LLMClient(Protocol):
    """Dependency-injection boundary used by application services."""

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model_tier: ModelTier,
        json_mode: bool = False,
        temperature: float | None = None,
        thinking: bool | None = None,
        max_tokens: int | None = None,
    ) -> str: ...


def resolve_model_name(config: AppConfig, model_tier: ModelTier) -> str:
    """Map a business tier to its provider-specific configured model."""
    if model_tier is ModelTier.FLASH:
        return config.deepseek_flash_model
    if model_tier is ModelTier.PRO:
        return config.deepseek_pro_model
    raise ValueError(f"Unsupported model tier: {model_tier!r}")


class DeepSeekLLMClient:
    """OpenAI-compatible DeepSeek adapter with explicit Flash/Pro routing."""

    def __init__(
        self,
        config: AppConfig | None = None,
        *,
        timeout_seconds: float = DEFAULT_LLM_TIMEOUT_SECONDS,
        transport: Any | None = None,
    ) -> None:
        self.config = config or load_config()
        self.timeout_seconds = timeout_seconds
        self._transport = transport
        self._transport_lock = threading.Lock()

    def _get_transport(self) -> Any:
        if not self.config.has_api_key:
            raise LLMConfigurationError(
                "AI analysis is not configured yet. Add a DeepSeek API key."
            )
        if self._transport is None:
            with self._transport_lock:
                if self._transport is None:
                    self._transport = OpenAI(
                        api_key=self.config.deepseek_api_key,
                        base_url=self.config.deepseek_base_url,
                        timeout=self.timeout_seconds,
                        max_retries=0,
                    )
        return self._transport

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model_tier: ModelTier,
        json_mode: bool = False,
        temperature: float | None = None,
        thinking: bool | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Generate text without exposing provider model names to services."""
        transport = self._get_transport()
        resolved_model = resolve_model_name(self.config, model_tier)
        request: dict[str, Any] = {
            "model": resolved_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "max_tokens": max_tokens or DEFAULT_MAX_OUTPUT_TOKENS,
        }
        if json_mode:
            request["response_format"] = {"type": "json_object"}
        if temperature is not None:
            request["temperature"] = temperature
        if thinking is not None:
            request["extra_body"] = {
                "thinking": {"type": "enabled" if thinking else "disabled"}
            }

        logger.info(
            "LLM request prepared: tier=%s resolved_model=%s "
            "system_message_length=%d user_message_length=%d "
            "temperature=%s thinking=%s",
            model_tier.name,
            resolved_model,
            len(system_prompt),
            len(user_prompt),
            temperature,
            thinking,
        )
        try:
            response = transport.chat.completions.create(**request)
            content = response.choices[0].message.content or ""
            logger.info(
                "LLM response received: tier=%s content_length=%d",
                model_tier.name,
                len(content),
            )
            logger.info(
                "LLM response summary: response_is_empty=%s "
                "response_starts_with_object=%s",
                not bool(content.strip()),
                content.lstrip().startswith("{"),
            )
            return content
        except APITimeoutError as exc:
            logger.warning("LLM API request timed out tier=%s", model_tier.name)
            raise LLMTimeoutError(
                "The AI analysis request timed out. Please try again."
            ) from exc
        except RateLimitError as exc:
            logger.warning("LLM API rate limited tier=%s", model_tier.name)
            raise LLMRateLimitError(
                "The AI provider is busy. Please try again."
            ) from exc
        except OpenAIError as exc:
            logger.warning(
                "LLM API request failed tier=%s error_type=%s",
                model_tier.name,
                type(exc).__name__,
            )
            raise LLMRequestError(
                "The AI analysis request failed. Please try again."
            ) from exc
        except (AttributeError, IndexError, TypeError) as exc:
            logger.warning(
                "LLM response envelope was invalid tier=%s error_type=%s",
                model_tier.name,
                type(exc).__name__,
            )
            raise LLMRequestError(
                "The AI provider returned an unreadable response. Please try again."
            ) from exc
