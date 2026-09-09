"""Small test doubles; none perform network requests."""

from dataclasses import dataclass, field

from jobpilot.llm import ModelTier


@dataclass
class FakeLLMClient:
    responses: list[str]
    calls: list[dict] = field(default_factory=list)

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
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "model_tier": model_tier,
                "json_mode": json_mode,
                "temperature": temperature,
                "thinking": thinking,
                "max_tokens": max_tokens,
            }
        )
        if not self.responses:
            return ""
        return self.responses.pop(0)
