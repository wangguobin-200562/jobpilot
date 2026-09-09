from jobpilot.config import (
    AppConfig,
    DEFAULT_DEEPSEEK_BASE_URL,
    DEFAULT_DEEPSEEK_FLASH_MODEL,
    DEFAULT_DEEPSEEK_PRO_MODEL,
    load_config,
)


def test_config_loads_without_api_key(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "")
    monkeypatch.setenv("DEEPSEEK_FLASH_MODEL", "")
    monkeypatch.setenv("DEEPSEEK_PRO_MODEL", "")

    config = load_config()

    assert config.has_api_key is False
    assert config.deepseek_api_key is None
    assert config.deepseek_base_url == DEFAULT_DEEPSEEK_BASE_URL
    assert config.deepseek_flash_model == DEFAULT_DEEPSEEK_FLASH_MODEL
    assert config.deepseek_pro_model == DEFAULT_DEEPSEEK_PRO_MODEL


def test_config_repr_and_str_do_not_expose_api_key() -> None:
    config = AppConfig(
        deepseek_api_key="test-key",
        deepseek_base_url=DEFAULT_DEEPSEEK_BASE_URL,
        deepseek_flash_model=DEFAULT_DEEPSEEK_FLASH_MODEL,
        deepseek_pro_model=DEFAULT_DEEPSEEK_PRO_MODEL,
    )

    assert "test-key" not in repr(config)
    assert "test-key" not in str(config)
    assert "deepseek_api_key" not in repr(config)
