from pathlib import Path

from jobpilot.browser import ExtensionJobSiteAdapter, JobDiscoveryItem
from jobpilot.browser.models import discovery_items_to_batch_inputs


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_extension_payload_reuses_existing_batch_input_contract() -> None:
    discovered = JobDiscoveryItem(
        company="虚构公司",
        job_title="虚构岗位",
        source="boss",
        source_url="https://www.zhipin.com/job_detail/fake.html",
        jd_text="完整虚构 JD",
    )
    adapter = ExtensionJobSiteAdapter(lambda: [discovered])
    batch = discovery_items_to_batch_inputs(adapter.discover_jobs())
    assert batch[0].jd_text == discovered.jd_text
    assert batch[0].source_url == discovered.source_url


def test_discovery_layer_does_not_implement_matching_or_optimization() -> None:
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (PROJECT_ROOT / "src" / "jobpilot" / "browser").glob("*.py")
    )
    assert "class MatchingService" not in sources
    assert "class JobAnalyzer" not in sources
    assert "ResumeOptimizationService" not in sources


def test_discovery_scripts_have_no_apply_click_or_platform_secret_access() -> None:
    manifest = (PROJECT_ROOT / "extension" / "manifest.json").read_text(encoding="utf-8")
    scripts = "\n".join(
        (PROJECT_ROOT / "extension" / name).read_text(encoding="utf-8")
        for name in ("content.js", "background.js", "popup.js")
    )
    assert '"cookies"' not in manifest
    assert "chrome.cookies" not in scripts
    assert "localStorage" not in scripts
    assert "Authorization" not in scripts
    assert ".click(" not in scripts
    assert "MatchingService" not in scripts


def test_apply_script_is_manifested_but_has_no_platform_secret_access() -> None:
    manifest = (PROJECT_ROOT / "extension" / "manifest.json").read_text(encoding="utf-8")
    apply_script = (PROJECT_ROOT / "extension" / "boss_apply.js").read_text(
        encoding="utf-8"
    )

    assert '"boss_apply.js"' in manifest
    assert ".click(" in apply_script
    assert "document.cookie" not in apply_script
    assert "chrome.cookies" not in apply_script
    assert "localStorage" not in apply_script
    assert "webdriver" not in apply_script


def test_extension_explains_bridge_and_token_failures_separately() -> None:
    popup = (PROJECT_ROOT / "extension" / "popup.js").read_text(encoding="utf-8")
    assert "无法连接本地 JobPilot" in popup
    assert "连接令牌已失效" in popup
    assert "Extension 来源未通过本地校验" in popup
    assert "岗位数据未通过校验" in popup
    assert 'credentials: "omit"' in popup
    assert 'referrerPolicy: "no-referrer"' in popup


def test_confirmed_contact_auto_starts_from_mv3_background_tick() -> None:
    popup = (PROJECT_ROOT / "extension" / "popup.js").read_text(encoding="utf-8")
    background = (PROJECT_ROOT / "extension" / "background.js").read_text(
        encoding="utf-8"
    )
    manifest = (PROJECT_ROOT / "extension" / "manifest.json").read_text(
        encoding="utf-8"
    )

    assert "JOBPILOT_START_CONTACT" not in popup
    assert "JOBPILOT_BRIDGE_TICK" in background
    assert "JOBPILOT_CONTACT_BOSS" in background
    assert 'task.action === "initiate_contact"' in background
    assert "runOneApplyStep" in background
    assert "return true;" in background
    assert "chrome.alarms.onAlarm.addListener" in background
    assert '"alarms"' in manifest
    assert '"scripting"' in manifest
    assert "ensureBossAdapterReady" in background
    assert "chrome.scripting.executeScript" in background
    assert "maxRetries = 2" in background
    assert "reconcileBossContact" in background
    assert "while (" not in background
    assert "invalid_extension_origin" in background
    assert "Extension 来源未通过本地校验" in background


def test_contact_extension_never_generates_greeting_or_uploads_resume() -> None:
    sources = "\n".join(
        (PROJECT_ROOT / "extension" / name).read_text(encoding="utf-8")
        for name in ("background.js", "boss_apply.js", "popup.js")
    )
    lowered = sources.casefold()
    assert "deepseek" not in lowered
    assert "input[type='file']" in sources  # detection only; it triggers manual review
    assert "files =" not in lowered
    assert "upload" not in lowered
    assert "greeting" not in lowered
