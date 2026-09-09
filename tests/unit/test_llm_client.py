from types import SimpleNamespace

import httpx
from openai import APITimeoutError
import pytest

from jobpilot.config import (
    AppConfig,
    DEFAULT_DEEPSEEK_BASE_URL,
    DEFAULT_DEEPSEEK_FLASH_MODEL,
    DEFAULT_DEEPSEEK_PRO_MODEL,
)
from jobpilot.llm import (
    DeepSeekLLMClient,
    LLMConfigurationError,
    LLMTimeoutError,
    ModelTier,
)
from jobpilot.llm.client import resolve_model_name


def _config(api_key: str | None = "test-key") -> AppConfig:
    return AppConfig(
        deepseek_api_key=api_key,
        deepseek_base_url=DEFAULT_DEEPSEEK_BASE_URL,
        deepseek_flash_model=DEFAULT_DEEPSEEK_FLASH_MODEL,
        deepseek_pro_model=DEFAULT_DEEPSEEK_PRO_MODEL,
    )


def test_flash_tier_resolves_to_flash_model() -> None:
    assert resolve_model_name(_config(), ModelTier.FLASH) == "deepseek-v4-flash"


def test_pro_tier_resolves_to_pro_model() -> None:
    assert resolve_model_name(_config(), ModelTier.PRO) == "deepseek-v4-pro"


@pytest.mark.parametrize(
    ("tier", "expected_model"),
    [
        (ModelTier.FLASH, "deepseek-v4-flash"),
        (ModelTier.PRO, "deepseek-v4-pro"),
    ],
)
def test_client_routes_requests_to_configured_model(tier, expected_model) -> None:
    class Completions:
        request = None

        @classmethod
        def create(cls, **kwargs):
            cls.request = kwargs
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))]
            )

    transport = SimpleNamespace(chat=SimpleNamespace(completions=Completions))
    client = DeepSeekLLMClient(_config(), transport=transport)

    client.generate(
        system_prompt="Return JSON.",
        user_prompt="Test",
        model_tier=tier,
        json_mode=True,
    )

    assert Completions.request["model"] == expected_model
    assert Completions.request["response_format"] == {"type": "json_object"}


def test_client_sends_deterministic_non_thinking_json_request() -> None:
    class Completions:
        request = None

        @classmethod
        def create(cls, **kwargs):
            cls.request = kwargs
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))]
            )

    transport = SimpleNamespace(chat=SimpleNamespace(completions=Completions))
    client = DeepSeekLLMClient(_config(), transport=transport)

    client.generate(
        system_prompt="Return JSON.",
        user_prompt="Test",
        model_tier=ModelTier.FLASH,
        json_mode=True,
        temperature=0.0,
        thinking=False,
    )

    request = Completions.request
    assert request["model"] == "deepseek-v4-flash"
    assert request["response_format"] == {"type": "json_object"}
    assert request["temperature"] == 0.0
    assert request["extra_body"] == {"thinking": {"type": "disabled"}}
    assert request["max_tokens"] == 8192
    assert "top_p" not in request
    assert "max_completion_tokens" not in request


def test_missing_api_key_prevents_transport_request() -> None:
    class Transport:
        called = False

        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    Transport.called = True
                    return SimpleNamespace()

    client = DeepSeekLLMClient(_config(api_key=None), transport=Transport())

    with pytest.raises(LLMConfigurationError):
        client.generate(
            system_prompt="Return JSON.",
            user_prompt="Test",
            model_tier=ModelTier.FLASH,
            json_mode=True,
        )

    assert Transport.called is False


def test_provider_timeout_becomes_llm_timeout_error() -> None:
    class Completions:
        @staticmethod
        def create(**kwargs):
            raise APITimeoutError(httpx.Request("POST", "https://example.test"))

    transport = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    client = DeepSeekLLMClient(_config(), transport=transport)

    with pytest.raises(LLMTimeoutError):
        client.generate(
            system_prompt="Return JSON.",
            user_prompt="Test",
            model_tier=ModelTier.FLASH,
            json_mode=True,
        )
