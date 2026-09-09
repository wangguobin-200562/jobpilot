from pathlib import Path

from streamlit.testing.v1 import AppTest

from jobpilot.models import JobProfile
from jobpilot.storage import ApplicationRepository


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_home_page_runs_with_real_repository_data(tmp_path, monkeypatch) -> None:
    database = tmp_path / "jobpilot.db"
    monkeypatch.setenv("JOBPILOT_DATABASE_PATH", str(database))
    repository = ApplicationRepository(database)
    repository.create_application(
        company="示例科技",
        job_title="AI 实习生",
        jd_text="Python AI 应用开发",
        job_profile=JobProfile(job_title="AI 实习生", company="示例科技"),
        match_score=86,
    )
    repository.create_application(
        company="远景数据",
        job_title="数据实习生",
        jd_text="SQL 数据分析",
        job_profile=JobProfile(job_title="数据实习生", company="远景数据"),
        status="interviewing",
        match_score=80,
    )

    app = AppTest.from_file(PROJECT_ROOT / "app.py").run(timeout=10)

    assert not app.exception
    assert app.title[0].value == "求职看板"
    assert len(app.metric) == 6
    assert any(metric.label == "平均匹配度" for metric in app.metric)
    assert any(metric.label == "面试率" and metric.value == "—" for metric in app.metric)
    assert len(app.segmented_control) == 1
    assert len(app.dataframe) == 1
    assert len(app.dataframe[0].value) == 2

    app.segmented_control[0].set_value("面试中").run(timeout=10)

    assert not app.exception
    assert len(app.dataframe[0].value) == 1
