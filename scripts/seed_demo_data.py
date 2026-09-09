"""Optionally seed the local database with fully fictional portfolio demo data."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from jobpilot.models import JobProfile, MatchResult, MatchScoreBreakdown  # noqa: E402
from jobpilot.storage import ApplicationRepository  # noqa: E402


DEMO_SOURCE = "demo"
DEMO_APPLICATIONS = (
    {
        "company": "云舟智研（虚构）",
        "job_title": "AI 应用开发实习生",
        "location": "深圳",
        "status": "interviewing",
        "match_score": 88,
        "jd_text": (
            "这是 JobPilot 演示用的虚构岗位。负责使用 Python 和 FastAPI 开发 AI 应用，"
            "接入 LLM API，并使用 Git 协作；有 Docker 实践经验者优先。"
        ),
        "required_skills": ["Python", "FastAPI", "LLM API"],
        "preferred_skills": ["Docker"],
        "tools": ["Git", "Docker"],
        "missing_skills": [
            {"skill": "Docker", "importance": "preferred", "reason": "演示画像中暂无直接证据。"}
        ],
    },
    {
        "company": "星桥智能（虚构）",
        "job_title": "AI Agent 工程实习生",
        "location": "上海",
        "status": "contacted",
        "match_score": 81,
        "jd_text": (
            "这是 JobPilot 演示用的虚构岗位。参与 Agent Workflow 与工具调用功能开发，"
            "要求掌握 Python 和 Prompt Engineering，了解 LangGraph 更佳。"
        ),
        "required_skills": ["Python", "Agent Workflow", "Prompt Engineering"],
        "preferred_skills": ["LangGraph"],
        "tools": ["Git", "Linux"],
        "missing_skills": [
            {"skill": "LangGraph", "importance": "preferred", "reason": "演示画像中暂无直接证据。"}
        ],
    },
    {
        "company": "澄明数据（虚构）",
        "job_title": "数据分析实习生",
        "location": "北京",
        "status": "applied",
        "match_score": 72,
        "jd_text": (
            "这是 JobPilot 演示用的虚构岗位。负责业务数据整理与分析，要求掌握 SQL、"
            "Python 和数据可视化；具备 Tableau 使用经验者优先。"
        ),
        "required_skills": ["SQL", "Python", "数据可视化"],
        "preferred_skills": ["Tableau"],
        "tools": ["SQL", "Tableau"],
        "missing_skills": [
            {"skill": "Tableau", "importance": "preferred", "reason": "演示画像中暂无直接证据。"}
        ],
    },
    {
        "company": "远帆模型工坊（虚构）",
        "job_title": "LLM 应用开发实习生",
        "location": "杭州",
        "status": "saved",
        "match_score": 64,
        "jd_text": (
            "这是 JobPilot 演示用的虚构岗位。协助开发 RAG 与知识库问答功能，"
            "要求掌握 Python，了解 Embedding、向量数据库和模型 API。"
        ),
        "required_skills": ["Python", "RAG", "Embedding"],
        "preferred_skills": ["向量数据库"],
        "tools": ["LLM API", "向量数据库"],
        "missing_skills": [
            {"skill": "RAG", "importance": "required", "reason": "演示画像中暂无直接证据。"},
            {"skill": "向量数据库", "importance": "preferred", "reason": "演示画像中暂无直接证据。"},
        ],
    },
)


def seed_demo_data(
    repository: ApplicationRepository | None = None,
) -> tuple[int, int]:
    """Create missing demo records and return ``(created, skipped)``."""
    repository = repository or ApplicationRepository()
    created_count = 0
    skipped_count = 0

    for item in DEMO_APPLICATIONS:
        duplicate = repository.find_duplicate(
            company=item["company"],
            job_title=item["job_title"],
            jd_text=item["jd_text"],
        )
        if duplicate is not None:
            skipped_count += 1
            continue

        profile = JobProfile(
            company=item["company"],
            job_title=item["job_title"],
            location=item["location"],
            responsibilities=["完成该虚构岗位描述中的开发或分析任务。"],
            required_skills=item["required_skills"],
            preferred_skills=item["preferred_skills"],
            tools_and_technologies=item["tools"],
        )
        score = item["match_score"]
        match = MatchResult(
            scores=MatchScoreBreakdown(overall_score=score),
            missing_skills=item["missing_skills"],
            strengths=["该记录仅用于演示 JobPilot 的本地数据体验。"],
            gaps=[entry["reason"] for entry in item["missing_skills"]],
            summary="完全虚构的 Demo 匹配结果。",
        )
        application = repository.create_application(
            company=item["company"],
            job_title=item["job_title"],
            location=item["location"],
            jd_text=item["jd_text"],
            job_profile=profile,
            match_score=score,
            match_result=match,
            source=DEMO_SOURCE,
        )
        target_status = item["status"]
        if target_status != "saved":
            repository.update_status(application.id, "applied")
            if target_status != "applied":
                repository.update_status(application.id, target_status)
        created_count += 1

    return created_count, skipped_count


def main() -> None:
    created, skipped = seed_demo_data()
    print(f"Created {created} demo applications.")
    print(f"Skipped {skipped} existing demo applications.")


if __name__ == "__main__":
    main()
