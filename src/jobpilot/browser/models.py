"""Validated contracts for BOSS job discovery."""

from datetime import datetime, timezone

from pydantic import Field, model_validator

from jobpilot.models import BatchJobInput, ProfileModel
from jobpilot.browser.job_identity import canonical_job_key, canonicalize_job_url


class JobDiscoveryItem(ProfileModel):
    company: str | None = None
    job_title: str | None = None
    location: str | None = None
    salary: str | None = None
    source: str = Field(default="boss", min_length=1, max_length=40)
    source_url: str = Field(min_length=1, max_length=2_048)
    jd_text: str = Field(min_length=1, max_length=100_000)
    discovered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    capture_event_id: str | None = Field(default=None, min_length=8, max_length=100)
    canonical_job_key: str | None = Field(default=None, min_length=5, max_length=2_100)

    @model_validator(mode="after")
    def normalize_identity(self) -> "JobDiscoveryItem":
        self.source_url = canonicalize_job_url(self.source_url) or self.source_url
        self.canonical_job_key = canonical_job_key(
            self.source_url, self.company, self.job_title
        )
        return self


class JobDiscoveryFailure(ProfileModel):
    index: int = Field(ge=1)
    company: str | None = None
    job_title: str | None = None
    error_message: str


class JobDiscoveryResult(ProfileModel):
    items: list[JobDiscoveryItem] = Field(max_length=20)
    failures: list[JobDiscoveryFailure] = Field(default_factory=list)
    discovered_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)


def discovery_items_to_batch_inputs(items: list[JobDiscoveryItem]) -> list[BatchJobInput]:
    """Convert browser output directly to the established batch contract."""
    return [
        BatchJobInput(
            index=index,
            company=item.company,
            job_title=item.job_title,
            location=item.location,
            source_url=item.source_url,
            jd_text=item.jd_text,
            raw_block=item.jd_text,
        )
        for index, item in enumerate(items, 1)
    ]
