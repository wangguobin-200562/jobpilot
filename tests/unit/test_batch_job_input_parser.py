import pytest

from jobpilot.services import (
    BatchJobCountError,
    EmptyBatchJobError,
    parse_batch_job_input,
)


def _blocks(count: int) -> str:
    return "\n---\n".join(
        f"公司：虚构公司{i}\n岗位：岗位{i}\nJD：这是第 {i} 个完整岗位描述，包含职责、技能要求和工作内容。"
        for i in range(1, count + 1)
    )


def test_parse_two_valid_jobs() -> None:
    items = parse_batch_job_input(_blocks(2))
    assert len(items) == 2
    assert [item.index for item in items] == [1, 2]


def test_twenty_jobs_are_allowed() -> None:
    assert len(parse_batch_job_input(_blocks(20))) == 20


def test_twenty_one_jobs_are_rejected() -> None:
    with pytest.raises(BatchJobCountError, match="最多"):
        parse_batch_job_input(_blocks(21))


def test_single_job_is_supported_by_unified_screening() -> None:
    assert len(parse_batch_job_input(_blocks(1))) == 1


def test_separator_must_be_its_own_line() -> None:
    items = parse_batch_job_input(
        "第一份完整岗位描述，包含 Python 开发工作。\n  ---  \n第二份完整岗位描述，包含 SQL 分析工作。"
    )
    assert len(items) == 2


def test_metadata_is_parsed() -> None:
    first = parse_batch_job_input(
        "公司：显式公司\n岗位名称：显式岗位\n工作地点：广州\nJD：完整岗位职责与技能要求。"
        "\n---\n第二份完整岗位描述，包含足够岗位信息。"
    )[0]
    assert first.company == "显式公司"
    assert first.job_title == "显式岗位"
    assert first.location == "广州"
    assert first.jd_text == "完整岗位职责与技能要求。"


def test_plain_jd_without_metadata_is_allowed() -> None:
    items = parse_batch_job_input(
        "第一份只有正文的完整岗位描述。\n---\n第二份只有正文的完整岗位描述。"
    )
    assert items[0].company is None
    assert items[0].jd_text.startswith("第一份")


def test_metadata_only_block_rejects_empty_jd() -> None:
    with pytest.raises(EmptyBatchJobError, match="第 1 个岗位"):
        parse_batch_job_input("公司：虚构公司\n岗位：虚构岗位\n---\n第二份完整岗位描述。")


def test_source_url_is_optional_and_never_opened() -> None:
    items = parse_batch_job_input(
        "链接：https://example.com/job/1\nJD：第一份完整岗位描述。"
        "\n---\nJD：第二份完整岗位描述。"
    )
    assert items[0].source_url == "https://example.com/job/1"
    assert items[1].source_url is None


def test_jd_whitespace_is_normalized() -> None:
    first = parse_batch_job_input(
        "JD：  第一行  \n\n  第二行  \n---\nJD：另一份岗位正文。"
    )[0]
    assert first.jd_text == "第一行\n第二行"
