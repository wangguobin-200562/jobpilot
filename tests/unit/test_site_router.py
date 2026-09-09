import pytest

from jobpilot.browser import (
    ApplyMode,
    ContactMode,
    DiscoveryMode,
    ExtensionJobSiteAdapter,
    JobDiscoveryItem,
    PlaywrightJobSiteAdapter,
    ResumeSubmissionMode,
    require_discovery_mode,
    resolve_site_capability,
)


def _job(index: int = 1) -> JobDiscoveryItem:
    return JobDiscoveryItem(
        company="虚构公司",
        job_title=f"虚构岗位{index}",
        source="boss",
        source_url=f"https://www.zhipin.com/job_detail/fake-{index}.html",
        jd_text="完整虚构 JD",
    )


def test_boss_routes_to_extension() -> None:
    capability = resolve_site_capability("BOSS")
    assert capability.discovery_mode is DiscoveryMode.EXTENSION
    assert capability.auto_navigation is False
    assert capability.contact_mode is ContactMode.EXTENSION
    assert capability.resume_submission is ResumeSubmissionMode.MANUAL
    assert capability.apply_mode is ApplyMode.UNSUPPORTED


def test_generic_playwright_routes_to_playwright() -> None:
    assert (
        resolve_site_capability("generic_playwright").discovery_mode
        is DiscoveryMode.PLAYWRIGHT
    )


def test_unknown_site_is_unsupported() -> None:
    assert resolve_site_capability("unknown").discovery_mode is DiscoveryMode.UNSUPPORTED


def test_router_never_silently_falls_back() -> None:
    with pytest.raises(ValueError, match="uses extension"):
        require_discovery_mode("boss", DiscoveryMode.PLAYWRIGHT)


def test_both_adapters_return_the_unified_model() -> None:
    class Manager:
        def discover_current_page(self, *, limit):
            return type("Result", (), {"items": [_job()]})()

    playwright = PlaywrightJobSiteAdapter(Manager())
    extension = ExtensionJobSiteAdapter(lambda: [_job()])
    assert isinstance(playwright.discover_jobs()[0], JobDiscoveryItem)
    assert isinstance(extension.discover_jobs()[0], JobDiscoveryItem)
