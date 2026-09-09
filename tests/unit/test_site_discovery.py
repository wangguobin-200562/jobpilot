from datetime import datetime, timezone

from jobpilot.browser import JobDiscoveryItem
from jobpilot.ui.site_discovery import _build_received_result


class PreReloadItem:
    """Mimic a Pydantic instance created before a Streamlit module reload."""

    def model_dump(self, *, mode):
        assert mode == "python"
        return {
            "company": "虚构公司",
            "job_title": "虚构岗位",
            "location": "广州",
            "salary": None,
            "source": "boss",
            "source_url": "https://www.zhipin.com/job_detail/fake.html",
            "jd_text": "完整虚构 JD",
            "discovered_at": datetime.now(timezone.utc),
        }


def test_received_items_are_revalidated_across_hot_reload_boundary() -> None:
    result = _build_received_result([PreReloadItem()])
    assert result.discovered_count == 1
    assert isinstance(result.items[0], JobDiscoveryItem)
