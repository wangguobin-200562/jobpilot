import logging

from jobpilot.browser import BossExtractor, JobDiscoveryItem, discovery_items_to_batch_inputs
from jobpilot.browser.boss_extractor import DiscoveryHaltError, MAX_DISCOVERY_JOBS


class Node:
    def __init__(self, *, text=None, attrs=None, children=None):
        self.text = text
        self.attrs = attrs or {}
        self.children = children or {}

    def locator(self, selector):
        return Locator(self.children.get(selector, []))

    def inner_text(self, timeout=None):
        return self.text or ""

    def get_attribute(self, name, timeout=None):
        return self.attrs.get(name)


class Locator:
    def __init__(self, items):
        self.items = items

    def count(self):
        return len(self.items)

    @property
    def first(self):
        return self.items[0]

    def nth(self, index):
        return self.items[index]


def _card(index, *, company=True, url=None):
    selectors = BossExtractor().selectors
    return Node(children={
        selectors.company[0]: [Node(text=f"虚构公司{index}")] if company else [],
        selectors.job_title[0]: [Node(text=f"Python 岗位{index}")],
        selectors.location[0]: [Node(text="广州")],
        selectors.salary[0]: [Node(text="10-15K")],
        selectors.job_link[0]: [Node(attrs={"href": url or f"/job_detail/fake-{index}.html"})],
    })


def _page(cards):
    selectors = BossExtractor().selectors
    return Node(children={selectors.job_cards[0]: cards})


def test_extracts_job_card_fields_and_normalizes_url() -> None:
    card = BossExtractor().extract_job_cards(_page([_card(1)]))[0]
    assert card == {
        "company": "虚构公司1", "job_title": "Python 岗位1", "location": "广州",
        "salary": "10-15K", "source_url": "https://www.zhipin.com/job_detail/fake-1.html",
    }


def test_extracts_jd_and_missing_optional_fields_are_none() -> None:
    extractor = BossExtractor()
    page = Node(children={extractor.selectors.job_description[0]: [Node(text="  完整的虚构 JD  \n 要求 Python  ")]})
    assert extractor.extract_jd(page) == "完整的虚构 JD 要求 Python"
    card = extractor.extract_job_cards(_page([_card(1, company=False)]))[0]
    assert card["company"] is None


def test_selector_fallback_and_selector_failure() -> None:
    extractor = BossExtractor()
    fallback = Node(children={extractor.selectors.job_cards[1]: [_card(1)]})
    assert len(extractor.extract_job_cards(fallback)) == 1
    try:
        extractor.extract_job_cards(Node())
    except Exception as exc:
        assert "页面结构可能已变化" in str(exc)
    else:
        raise AssertionError("selector failure must be reported")


def test_one_detail_failure_does_not_stop_batch() -> None:
    def loader(url):
        if "fake-2" in url:
            raise RuntimeError("private browser token")
        return "完整虚构岗位描述，要求 Python 开发与测试。"

    result = BossExtractor().discover(_page([_card(1), _card(2), _card(3)]), loader)
    assert result.discovered_count == 2
    assert result.failed_count == 1
    assert "token" not in result.failures[0].error_message


def test_deduplicates_by_url_and_company_title() -> None:
    same_url = "/job_detail/same.html"
    cards = [_card(1, url=same_url), _card(2, url=same_url), _card(1, url="/job_detail/other.html")]
    result = BossExtractor().discover(_page(cards), lambda url: "足够完整的虚构职位描述。")
    assert result.discovered_count == 1


def test_discovery_is_capped_at_twenty() -> None:
    cards = [_card(index) for index in range(1, 26)]
    result = BossExtractor().discover(_page(cards), lambda url: "足够完整的虚构职位描述。", limit=99)
    assert result.discovered_count == MAX_DISCOVERY_JOBS


def test_conversion_to_existing_batch_input_preserves_fields() -> None:
    item = JobDiscoveryItem(
        company="虚构公司", job_title="虚构岗位", location="深圳", salary="12K",
        source_url="https://www.zhipin.com/job_detail/fake.html", jd_text="完整虚构 JD",
    )
    batch = discovery_items_to_batch_inputs([item])[0]
    assert batch.company == item.company
    assert batch.source_url == item.source_url
    assert batch.jd_text == item.jd_text


def test_unsafe_url_is_failed_without_opening_detail() -> None:
    called = False

    def loader(url):
        nonlocal called
        called = True
        return "不应调用"

    result = BossExtractor().discover(_page([_card(1, url="https://evil.example/job")]), loader)
    assert result.failed_count == 1
    assert called is False


def test_logs_exclude_jd_url_and_sensitive_browser_values(caplog) -> None:
    caplog.set_level(logging.INFO)
    secret = "cookie-secret-value"
    jd = "非常私密的完整虚构 JD"
    result = BossExtractor().discover(_page([_card(1)]), lambda url: jd)
    assert result.discovered_count == 1
    logs = caplog.text
    assert jd not in logs
    assert secret not in logs
    assert "fake-1" not in logs


def test_human_verification_signal_stops_discovery() -> None:
    def loader(url):
        raise DiscoveryHaltError("人工处理")

    try:
        BossExtractor().discover(_page([_card(1), _card(2)]), loader)
    except DiscoveryHaltError:
        pass
    else:
        raise AssertionError("human verification must pause discovery")
