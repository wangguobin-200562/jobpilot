"""Lightweight environment-backed configuration for JobPilot."""

from dataclasses import dataclass, field
import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_FLASH_MODEL = "deepseek-v4-flash"
DEFAULT_DEEPSEEK_PRO_MODEL = "deepseek-v4-pro"


def _optional_env(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return value or None


@dataclass(frozen=True, slots=True)
class AppConfig:
    deepseek_api_key: str | None = field(repr=False)
    deepseek_base_url: str
    deepseek_flash_model: str
    deepseek_pro_model: str

    @property
    def has_api_key(self) -> bool:
        """Return whether an API key is available without requiring one."""
        return self.deepseek_api_key is not None


def load_config() -> AppConfig:
    """Load local environment values; missing optional values remain harmless."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    return AppConfig(
        deepseek_api_key=_optional_env("DEEPSEEK_API_KEY"),
        deepseek_base_url=(
            _optional_env("DEEPSEEK_BASE_URL") or DEFAULT_DEEPSEEK_BASE_URL
        ),
        deepseek_flash_model=(
            _optional_env("DEEPSEEK_FLASH_MODEL") or DEFAULT_DEEPSEEK_FLASH_MODEL
        ),
        deepseek_pro_model=(
            _optional_env("DEEPSEEK_PRO_MODEL") or DEFAULT_DEEPSEEK_PRO_MODEL
        ),
    )
