"""User-driven browser automation boundaries for JobPilot."""

from jobpilot.browser.boss_browser import (
    BossBrowserError,
    BossBrowserManager,
    BossLoginRequiredError,
    HumanVerificationRequired,
)
from jobpilot.browser.boss_extractor import BossExtractor, BossSelectors
from jobpilot.browser.models import (
    JobDiscoveryFailure,
    JobDiscoveryItem,
    JobDiscoveryResult,
    discovery_items_to_batch_inputs,
)
from jobpilot.browser.adapters import (
    ExtensionJobSiteAdapter,
    JobSiteAdapter,
    PlaywrightJobSiteAdapter,
)
from jobpilot.browser.extension_bridge import (
    ExtensionBridgeError,
    ExtensionBridgeServer,
    ExtensionInbox,
    ExtensionPayload,
)
from jobpilot.browser.apply_channel import (
    HEARTBEAT_TIMEOUT_SECONDS,
    ApplyChannelDiagnostics,
    ApplyChannelError,
    ApplyTaskChannel,
)
from jobpilot.browser.site_capabilities import (
    ApplyMode,
    ContactMode,
    DiscoveryMode,
    ResumeSubmissionMode,
    SiteCapability,
)
from jobpilot.browser.site_router import require_discovery_mode, resolve_site_capability

__all__ = [
    "BossBrowserError", "BossBrowserManager", "BossExtractor", "BossLoginRequiredError",
    "BossSelectors", "HumanVerificationRequired", "JobDiscoveryFailure",
    "JobDiscoveryItem", "JobDiscoveryResult", "discovery_items_to_batch_inputs",
    "DiscoveryMode", "ExtensionBridgeError", "ExtensionBridgeServer",
    "ApplyMode",
    "ContactMode", "ResumeSubmissionMode",
    "ApplyChannelError", "ApplyTaskChannel",
    "ApplyChannelDiagnostics", "HEARTBEAT_TIMEOUT_SECONDS",
    "ExtensionInbox", "ExtensionJobSiteAdapter", "ExtensionPayload",
    "JobSiteAdapter", "PlaywrightJobSiteAdapter", "SiteCapability",
    "require_discovery_mode", "resolve_site_capability",
]
