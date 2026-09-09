"""Explicit site capability registry; routing happens before discovery."""

from dataclasses import dataclass
from enum import Enum


class DiscoveryMode(str, Enum):
    PLAYWRIGHT = "playwright"
    EXTENSION = "extension"
    UNSUPPORTED = "unsupported"


class ApplyMode(str, Enum):
    EXTENSION = "extension"
    UNSUPPORTED = "unsupported"


class ContactMode(str, Enum):
    EXTENSION = "extension"
    UNSUPPORTED = "unsupported"


class ResumeSubmissionMode(str, Enum):
    MANUAL = "manual"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class SiteCapability:
    site: str
    discovery_mode: DiscoveryMode
    auto_navigation: bool
    apply_mode: ApplyMode = ApplyMode.UNSUPPORTED
    contact_mode: ContactMode = ContactMode.UNSUPPORTED
    resume_submission: ResumeSubmissionMode = ResumeSubmissionMode.UNSUPPORTED


SITE_CAPABILITIES: dict[str, SiteCapability] = {
    "boss": SiteCapability(
        site="boss",
        discovery_mode=DiscoveryMode.EXTENSION,
        auto_navigation=False,
        apply_mode=ApplyMode.UNSUPPORTED,
        contact_mode=ContactMode.EXTENSION,
        resume_submission=ResumeSubmissionMode.MANUAL,
    ),
    "generic_playwright": SiteCapability(
        site="generic_playwright",
        discovery_mode=DiscoveryMode.PLAYWRIGHT,
        auto_navigation=True,
        apply_mode=ApplyMode.UNSUPPORTED,
    ),
}
