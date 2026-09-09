"""Canonical, privacy-safe job identity helpers shared across workflow layers."""

from __future__ import annotations

from hashlib import sha256
from urllib.parse import urlsplit, urlunsplit


def canonicalize_job_url(source_url: str | None) -> str | None:
    """Normalize a public job URL without retaining tracking parameters."""
    if not source_url:
        return None
    value = source_url.strip()
    if not value:
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return value
    hostname = (parsed.hostname or "").casefold()
    if not hostname:
        return value
    if hostname == "zhipin.com" or hostname.endswith(".zhipin.com"):
        hostname = "www.zhipin.com"
    port = f":{parsed.port}" if parsed.port else ""
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((parsed.scheme.casefold(), f"{hostname}{port}", path, "", ""))


def canonical_job_key(
    source_url: str | None,
    company: str | None,
    job_title: str | None,
) -> str:
    canonical_url = canonicalize_job_url(source_url)
    if canonical_url:
        return f"url:{canonical_url.casefold()}"
    normalized_company = " ".join((company or "").split()).casefold()
    normalized_title = " ".join((job_title or "").split()).casefold()
    return f"name:{normalized_company}|{normalized_title}"


def safe_job_key(job_key: str) -> str:
    """Return a short opaque identifier suitable for diagnostics."""
    return sha256(job_key.encode("utf-8")).hexdigest()[:12]
