import json
from pathlib import Path
import subprocess

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNNER = PROJECT_ROOT / "tests" / "fixtures" / "run_boss_apply_fixture.js"
SCRIPT = PROJECT_ROOT / "extension" / "boss_apply.js"
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "boss_apply"


def _run(name: str, mode: str = "inspect") -> dict:
    completed = subprocess.run(
        ["node", str(RUNNER), str(FIXTURES / name), str(SCRIPT), mode],
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )
    return json.loads(completed.stdout)


@pytest.mark.parametrize(
    ("fixture", "status"),
    [
        ("normal.html", "ready"),
        ("already_applied.html", "already_contacted"),
        ("closed.html", "skipped"),
        ("captcha.html", "manual_required"),
        ("extra_form.html", "manual_required"),
        ("missing_selector.html", "failed"),
        ("success.html", "contacted"),
    ],
)
def test_offline_boss_apply_states(fixture, status) -> None:
    mode = "after" if fixture == "success.html" else "inspect"
    assert _run(fixture, mode)["status"] == status


def test_confirmed_action_requires_explicit_conversation_before_contacted() -> None:
    result = _run("normal.html", "execute")
    assert result["status"] == "contacted"
    assert result["contact_button_clicked"] is True
    assert result["contact_success_detected"] is True
    assert result["conversation_found"] is True


def test_existing_conversation_is_not_clicked_or_greeted_again() -> None:
    result = _run("already_applied.html")
    assert result["status"] == "already_contacted"
    assert result["contact_button_clicked"] is False
    assert result["conversation_found"] is True


def test_adapter_only_clicks_native_contact_and_never_writes_a_message() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert '/^立即沟通$/' in source
    assert ".value =" not in source
    assert "textContent =" not in source
    assert "innerText =" not in source
    assert "DeepSeek" not in source
    assert "resume" not in source.casefold()


def test_adapter_contains_no_anti_detection_or_credential_access() -> None:
    source = SCRIPT.read_text(encoding="utf-8").casefold()
    forbidden = (
        "document.cookie",
        "localstorage",
        "authorization",
        "webdriver",
        "fingerprint",
        "captcha bypass",
    )
    assert all(term not in source for term in forbidden)
