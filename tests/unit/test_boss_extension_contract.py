import json
from pathlib import Path
import subprocess


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNNER = PROJECT_ROOT / "tests" / "fixtures" / "run_boss_extension_fixture.js"
CONTENT_SCRIPT = PROJECT_ROOT / "extension" / "content.js"


def _extract(cards, **extra):
    completed = subprocess.run(
        ["node", str(RUNNER), str(CONTENT_SCRIPT)],
        input=json.dumps({"cards": cards, **extra}),
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )
    return json.loads(completed.stdout)


def _card(index=1, **changes):
    value = {
        "company": f"虚构公司{index}",
        "job_title": f"虚构岗位{index}",
        "location": "广州",
        "salary": "10-15K",
        "source_url": f"/job_detail/fake-{index}.html",
        "jd_text": f"第{index}份完整虚构 JD",
    }
    value.update(changes)
    return value


def test_current_boss_job_is_extracted() -> None:
    result = _extract([_card()], active_index=0, detail_jd="当前岗位完整虚构 JD")
    assert result["jobs"][0]["jd_text"] == "当前岗位完整虚构 JD"
    assert result["jobs"][0]["source"] == "boss"


def test_multiple_visible_jobs_are_extracted() -> None:
    result = _extract([_card(1), _card(2), _card(3)])
    assert len(result["jobs"]) == 3


def test_missing_company_and_salary_are_allowed() -> None:
    card = _card()
    del card["company"]
    del card["salary"]
    result = _extract([card])
    assert result["jobs"][0]["company"] is None
    assert result["jobs"][0]["salary"] is None


def test_missing_jd_is_failed_without_stopping_other_jobs() -> None:
    card = _card(1)
    del card["jd_text"]
    result = _extract([card, _card(2)])
    assert len(result["jobs"]) == 1
    assert result["failures"][0]["reason"] == "missing_jd"


def test_duplicate_jobs_are_removed() -> None:
    result = _extract([_card(1), _card(1)])
    assert len(result["jobs"]) == 1


def test_extension_caps_results_at_twenty() -> None:
    result = _extract([_card(index) for index in range(1, 24)])
    assert len(result["jobs"]) == 20


def test_card_text_fallback_extracts_company_and_location() -> None:
    card = _card()
    del card["company"]
    del card["location"]
    card["lines"] = [
        "Agent研发工程师 - 飞书", "20-30K", "在校/应届", "硕士",
        "字节跳动", "深圳·南山区·科技园",
    ]
    result = _extract([card])
    assert result["jobs"][0]["company"] == "字节跳动"
    assert result["jobs"][0]["location"] == "深圳·南山区·科技园"


def test_protected_salary_glyphs_are_not_forwarded_as_garbled_text() -> None:
    result = _extract([_card(salary="\ue001\ue002-\ue003\ue004K")])
    assert result["jobs"][0]["salary"] is None


def test_text_fallback_splits_company_location_and_extracts_salary() -> None:
    card = _card()
    del card["company"]
    del card["location"]
    del card["salary"]
    card["lines"] = [
        "Agent研发工程师",
        "20-35K·15薪",
        "在校/应届",
        "字节跳动 深圳·南山区·科技园",
    ]
    result = _extract([card])
    assert result["jobs"][0]["company"] == "字节跳动"
    assert result["jobs"][0]["location"] == "深圳·南山区·科技园"
    assert result["jobs"][0]["salary"] == "20-35K·15薪"


def test_jd_uses_visible_text_instead_of_hidden_style_content() -> None:
    card = _card(
        jd_text=(
            "举报微信扫码分享不合适职位描述JavaDocker"
            ".hidden{display:none!important;}真实岗位职责"
        ),
        jd_visible_text=(
            "职位描述\n微信扫码分享\n举报\nJava Docker\n"
            "岗位职责\n负责 AI 应用开发\n任职要求\n熟悉 Python"
        ),
    )
    result = _extract([card])
    jd = result["jobs"][0]["jd_text"]

    assert "负责 AI 应用开发" in jd
    assert "熟悉 Python" in jd
    assert "display:none" not in jd
    assert "微信扫码分享" not in jd
    assert "举报" not in jd
