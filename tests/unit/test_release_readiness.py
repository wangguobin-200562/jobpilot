from pathlib import Path
import re

from jobpilot.config import (
    AppConfig,
    DEFAULT_DEEPSEEK_BASE_URL,
    DEFAULT_DEEPSEEK_FLASH_MODEL,
    DEFAULT_DEEPSEEK_PRO_MODEL,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_secret_and_local_data_files_are_ignored() -> None:
    patterns = set((PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines())

    assert ".env" in patterns
    assert ".venv/" in patterns
    assert "data/*.db" in patterns
    assert "logs/" in patterns
    assert "*.log" in patterns
    assert ".streamlit/secrets.toml" in patterns
    assert ".browser/" in patterns


def test_env_example_contains_placeholder_only() -> None:
    example = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")

    assert example.splitlines() == [
        "DEEPSEEK_API_KEY=",
        "DEEPSEEK_BASE_URL=",
        "DEEPSEEK_FLASH_MODEL=",
        "DEEPSEEK_PRO_MODEL=",
    ]


def test_api_key_is_not_visible_in_config_repr_or_str() -> None:
    fake_secret = "release-audit-test-key"
    config = AppConfig(
        deepseek_api_key=fake_secret,
        deepseek_base_url=DEFAULT_DEEPSEEK_BASE_URL,
        deepseek_flash_model=DEFAULT_DEEPSEEK_FLASH_MODEL,
        deepseek_pro_model=DEFAULT_DEEPSEEK_PRO_MODEL,
    )

    assert fake_secret not in repr(config)
    assert fake_secret not in str(config)


def test_runtime_code_has_no_machine_specific_absolute_path() -> None:
    files = [PROJECT_ROOT / "app.py"]
    files.extend((PROJECT_ROOT / "src").rglob("*.py"))
    files.extend((PROJECT_ROOT / "scripts").rglob("*.py"))

    for path in files:
        content = path.read_text(encoding="utf-8")
        assert re.search(r"(?<![A-Za-z])[A-Za-z]:[\\/]", content) is None, path


def test_release_documents_and_entrypoint_exist() -> None:
    assert (PROJECT_ROOT / "app.py").is_file()
    assert (PROJECT_ROOT / "README.md").is_file()
    assert (PROJECT_ROOT / "docs" / "SMOKE_TEST.md").is_file()
    assert (PROJECT_ROOT / "docs" / "screenshots" / ".gitkeep").is_file()
    assert (PROJECT_ROOT / "extension" / "manifest.json").is_file()
    assert (PROJECT_ROOT / "extension" / "content.js").is_file()


def test_requirements_has_no_local_install_path() -> None:
    requirements = (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8")

    assert "file://" not in requirements.casefold()
    assert re.search(r"(?<![A-Za-z])[A-Za-z]:[\\/]", requirements) is None
