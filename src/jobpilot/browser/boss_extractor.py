"""Tolerant DOM extraction for the current BOSS search result page."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
import logging
import re
from typing import Any
from urllib.parse import urljoin, urlparse

from jobpilot.browser.models import JobDiscoveryFailure, JobDiscoveryItem, JobDiscoveryResult


logger = logging.getLogger(__name__)
MAX_DISCOVERY_JOBS = 20
BOSS_ORIGIN = "https://www.zhipin.com"


@dataclass(frozen=True, slots=True)
class BossSelectors:
    """All change-prone BOSS selectors live in one place."""

    job_cards: tuple[str, ...] = (
        ".job-card-wrapper", ".job-list-box .job-card-box",
        ".search-job-result li.job-card-box", ".job-card-box",
    )
    job_title: tuple[str, ...] = (".job-name", ".job-title", "[class*='job-name']")
    company: tuple[str, ...] = (".company-name", ".company-text .name", "[class*='company-name']")
    location: tuple[str, ...] = (".job-area", ".job-address", "[class*='job-area']")
    salary: tuple[str, ...] = (".salary", ".job-salary", "[class*='salary']")
    job_link: tuple[str, ...] = ("a[href*='/job_detail/']", "a.job-card-left")
    job_description: tuple[str, ...] = (
        ".job-sec-text", ".job-detail-section .job-sec-text",
        ".job-detail-body", "[class*='job-description']",
    )
    verification: tuple[str, ...] = (
        ".verify-wrap", ".captcha-container", "[class*='captcha']", "[class*='verify']",
    )


class BossExtractionError(RuntimeError):
    """Safe extraction error without page contents."""


class DiscoveryHaltError(RuntimeError):
    """Signal that discovery must stop for explicit user action."""


def _clean(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip()
    return cleaned or None


def _first_text(scope: Any, selectors: tuple[str, ...]) -> str | None:
    for selector in selectors:
        try:
            locator = scope.locator(selector)
            if locator.count():
                value = _clean(locator.first.inner_text(timeout=2_000))
                if value:
                    return value
        except Exception:
            continue
    return None


def _first_attribute(scope: Any, selectors: tuple[str, ...], name: str) -> str | None:
    for selector in selectors:
        try:
            locator = scope.locator(selector)
            if locator.count():
                value = locator.first.get_attribute(name, timeout=2_000)
                if value:
                    return value.strip()
        except Exception:
            continue
    return None


def _safe_boss_job_url(value: str | None) -> str | None:
    if not value:
        return None
    absolute = urljoin(BOSS_ORIGIN, value)
    parsed = urlparse(absolute)
    if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith("zhipin.com"):
        return None
    return absolute


class BossExtractor:
    def __init__(self, selectors: BossSelectors | None = None) -> None:
        self.selectors = selectors or BossSelectors()

    def verification_visible(self, page: Any) -> bool:
        for selector in self.selectors.verification:
            try:
                if page.locator(selector).count():
                    return True
            except Exception:
                continue
        return False

    def extract_job_cards(self, page: Any) -> list[dict[str, str | None]]:
        cards = None
        for selector in self.selectors.job_cards:
            try:
                candidate = page.locator(selector)
                if candidate.count():
                    cards = candidate
                    break
            except Exception:
                continue
        if cards is None:
            raise BossExtractionError("未识别到职位列表，BOSS 页面结构可能已变化。")
        summaries: list[dict[str, str | None]] = []
        for index in range(min(cards.count(), MAX_DISCOVERY_JOBS)):
            card = cards.nth(index)
            summaries.append({
                "company": _first_text(card, self.selectors.company),
                "job_title": _first_text(card, self.selectors.job_title),
                "location": _first_text(card, self.selectors.location),
                "salary": _first_text(card, self.selectors.salary),
                "source_url": _safe_boss_job_url(_first_attribute(card, self.selectors.job_link, "href")),
            })
        return summaries

    def extract_jd(self, page: Any) -> str:
        jd = _first_text(page, self.selectors.job_description)
        if not jd:
            raise BossExtractionError("该岗位未提取到职位描述。")
        return jd

    def discover(
        self,
        page: Any,
        detail_loader: Callable[[str], str],
        *,
        limit: int = MAX_DISCOVERY_JOBS,
    ) -> JobDiscoveryResult:
        limit = max(1, min(limit, MAX_DISCOVERY_JOBS))
        summaries = self.extract_job_cards(page)[:limit]
        items: list[JobDiscoveryItem] = []
        failures: list[JobDiscoveryFailure] = []
        seen_urls: set[str] = set()
        seen_identity: set[tuple[str, str]] = set()
        for index, summary in enumerate(summaries, 1):
            url = summary["source_url"]
            identity = ((summary["company"] or "").casefold(), (summary["job_title"] or "").casefold())
            if (url and url in seen_urls) or (all(identity) and identity in seen_identity):
                continue
            if url:
                seen_urls.add(url)
            if all(identity):
                seen_identity.add(identity)
            try:
                if not url:
                    raise BossExtractionError("该岗位缺少可用详情链接。")
                jd_text = _clean(detail_loader(url))
                if not jd_text:
                    raise BossExtractionError("该岗位未提取到职位描述。")
                items.append(JobDiscoveryItem(**summary, jd_text=jd_text))
                logger.info(
                    "BOSS discovery item index=%d url_fingerprint_prefix=%s status=completed",
                    index, sha256(url.encode("utf-8")).hexdigest()[:12],
                )
            except DiscoveryHaltError:
                raise
            except Exception as exc:
                logger.warning(
                    "BOSS discovery item index=%d status=failed error_type=%s",
                    index, type(exc).__name__,
                )
                failures.append(JobDiscoveryFailure(
                    index=index, company=summary["company"], job_title=summary["job_title"],
                    error_message=(str(exc) if isinstance(exc, BossExtractionError) else "岗位详情读取失败。"),
                ))
        return JobDiscoveryResult(
            items=items, failures=failures,
            discovered_count=len(items), failed_count=len(failures),
        )
