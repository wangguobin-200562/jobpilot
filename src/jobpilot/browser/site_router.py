"""Deterministic site router with no failure-driven fallback."""

from jobpilot.browser.site_capabilities import (
    SITE_CAPABILITIES,
    ApplyMode,
    ContactMode,
    DiscoveryMode,
    ResumeSubmissionMode,
    SiteCapability,
)


def resolve_site_capability(site: str) -> SiteCapability:
    normalized = site.strip().casefold()
    return SITE_CAPABILITIES.get(
        normalized,
        SiteCapability(
            site=normalized or "unknown",
            discovery_mode=DiscoveryMode.UNSUPPORTED,
            auto_navigation=False,
            apply_mode=ApplyMode.UNSUPPORTED,
            contact_mode=ContactMode.UNSUPPORTED,
            resume_submission=ResumeSubmissionMode.UNSUPPORTED,
        ),
    )


def require_discovery_mode(site: str, expected: DiscoveryMode) -> SiteCapability:
    """Reject mismatched adapters instead of silently falling back."""
    capability = resolve_site_capability(site)
    if capability.discovery_mode is not expected:
        raise ValueError(
            f"site {capability.site!r} uses {capability.discovery_mode.value}, "
            f"not {expected.value}"
        )
    return capability
