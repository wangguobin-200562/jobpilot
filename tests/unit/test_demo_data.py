from jobpilot.models import JobProfile
from jobpilot.storage import ApplicationRepository
from scripts.clear_demo_data import clear_demo_data
from scripts.seed_demo_data import DEMO_APPLICATIONS, DEMO_SOURCE, seed_demo_data


def test_seed_creates_only_fictional_demo_records(tmp_path) -> None:
    repository = ApplicationRepository(tmp_path / "jobpilot.db")

    created, skipped = seed_demo_data(repository)
    applications = repository.list_applications()

    assert created == len(DEMO_APPLICATIONS)
    assert skipped == 0
    assert len(applications) == len(DEMO_APPLICATIONS)
    assert all(item.source == DEMO_SOURCE for item in applications)
    assert all("虚构" in item.company for item in applications)
    assert all(item.match_result is not None for item in applications)


def test_seed_is_idempotent(tmp_path) -> None:
    repository = ApplicationRepository(tmp_path / "jobpilot.db")

    first = seed_demo_data(repository)
    second = seed_demo_data(repository)

    assert first == (len(DEMO_APPLICATIONS), 0)
    assert second == (0, len(DEMO_APPLICATIONS))
    assert len(repository.list_applications()) == len(DEMO_APPLICATIONS)


def test_clear_removes_demo_records_only(tmp_path) -> None:
    repository = ApplicationRepository(tmp_path / "jobpilot.db")
    user_application = repository.create_application(
        company="用户测试公司",
        job_title="用户测试岗位",
        jd_text="这是一条普通本地测试岗位，不属于 Demo 数据。",
        job_profile=JobProfile(company="用户测试公司", job_title="用户测试岗位"),
        source="manual",
    )
    seed_demo_data(repository)

    removed = clear_demo_data(repository)
    remaining = repository.list_applications()

    assert removed == len(DEMO_APPLICATIONS)
    assert [item.id for item in remaining] == [user_application.id]
    assert remaining[0].source == "manual"

