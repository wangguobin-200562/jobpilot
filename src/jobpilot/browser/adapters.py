"""Small common adapter contract for job-site discovery sources."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from jobpilot.browser.models import JobDiscoveryItem


class JobSiteAdapter(Protocol):
    """Every discovery adapter returns the same validated downstream model."""

    def supports(self, site: str) -> bool: ...

    def discover_jobs(self, *, limit: int = 20) -> list[JobDiscoveryItem]: ...


class PlaywrightJobSiteAdapter:
    """Preserve the existing Playwright manager behind the common contract."""

    def __init__(self, manager: object, *, site: str = "generic_playwright") -> None:
        self._manager = manager
        self._site = site

    def supports(self, site: str) -> bool:
        return site.casefold() == self._site.casefold()

    def discover_jobs(self, *, limit: int = 20) -> list[JobDiscoveryItem]:
        result = self._manager.discover_current_page(limit=min(max(limit, 1), 20))
        return [item.model_copy(deep=True) for item in result.items]


class ExtensionJobSiteAdapter:
    """Read extension-delivered jobs without implementing a second analyzer."""

    def __init__(
        self,
        receiver: Callable[[], list[JobDiscoveryItem]],
        *,
        site: str = "boss",
    ) -> None:
        self._receiver = receiver
        self._site = site

    def supports(self, site: str) -> bool:
        return site.casefold() == self._site.casefold()

    def discover_jobs(self, *, limit: int = 20) -> list[JobDiscoveryItem]:
        bounded = min(max(limit, 1), 20)
        return [item.model_copy(deep=True) for item in self._receiver()[:bounded]]
