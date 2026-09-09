"""Safe five-job provider benchmark with fixed, PII-free inputs."""

from __future__ import annotations

import json
from time import perf_counter

from jobpilot.browser import JobDiscoveryItem, discovery_items_to_batch_inputs
from jobpilot.config import load_config
from jobpilot.llm import DeepSeekLLMClient
from jobpilot.models import CandidateProfile, ExperienceItem, ProjectItem, Skills
from jobpilot.services import FastScreeningPipeline, FastScreeningService, LocalPreScreenService, MatchingService


def _candidate() -> CandidateProfile:
    # Fixed, fictional and PII-free: timing is representative without using a user's resume.
    return CandidateProfile(
        skills=Skills(
            programming_languages=["Python"],
            frameworks=["FastAPI", "Flask", "LangChain"],
            tools=["Git", "Docker"],
            databases=["SQL", "PostgreSQL"],
            other=["LLM API", "RAG", "Prompt Engineering", "Agent Workflow"],
        ),
        experience=[ExperienceItem(
            position="AI 应用开发实习生",
            description="参与 Python 接口、智能工作流、数据处理和功能测试。",
            technologies=["Python", "FastAPI", "SQL"],
        )],
        projects=[ProjectItem(
            name="企业知识库问答",
            description="实现检索增强生成、接口封装和效果评估。",
            technologies=["Python", "LangChain", "PostgreSQL"],
        )],
    )


def _public_boss_jobs() -> list[JobDiscoveryItem]:
    source = "https://www.zhipin.com/zhaopin/dd42dc9941e0a6791X1y0tq0EQ~~/"
    records = [
        ("深信服科技", "JAVA/Python开发实习生", "深圳南山区西丽", "岗位职责：负责 AI Agent 系统开发和优化，包括记忆、规划和工具调用模块；开发基于大语言模型的智能体系统。任职要求：熟悉 Python 或 Java，理解 Agent 与 LLM，具备接口开发、测试和团队协作能力。"),
        ("盖亚青柯", "AI 开发工程师实习生", "深圳福田区车公庙", "岗位职责：参与 LLM Agent 核心系统设计与开发，完成工具调用、知识检索和后端接口能力。任职要求：熟悉 Python、FastAPI 或 Flask，理解大模型 API、RAG 和 Prompt Engineering，能够编写测试与技术文档。"),
        ("LynxAI", "Python实习生", "深圳南山区科技园", "岗位职责：使用 Flask、FastAPI 等 Python Web 框架进行后端服务开发与维护，设计 RESTful API，参与数据处理和服务测试。任职要求：熟悉 Python、Git 和数据库基础，具备良好的工程实践和沟通能力。"),
        ("数行者科技", "数据工程师（Python）实习生", "深圳福田区福田中心", "岗位职责：负责数据爬取与清洗、文本数据结构化、数据实时汇集与处理框架开发。任职要求：熟练掌握 Python，了解 Pandas、SQL 和数据处理流程，具备问题定位、测试和文档整理能力。"),
        ("深圳行为先教育科技", "AI Agent实习生", "深圳南山区科技园", "岗位职责：参与 AI Agent 的需求分析、场景设计与功能测试，协助优化 AI 对话流程、整理数据并撰写技术文档。任职要求：理解大模型应用，具备 Python 基础，对 Prompt、RAG 或工具调用有实践者优先。"),
    ]
    return [
        JobDiscoveryItem(
            company=company,
            job_title=title,
            location=location,
            source_url=f"{source}#job-{index}",
            jd_text=jd,
        )
        for index, (company, title, location, jd) in enumerate(records, 1)
    ]


def _summary(result, import_seconds: float) -> dict:
    metrics = result.metrics
    provider_timeline = [
        {
            "stage": item.stage,
            "job_index": item.job_index,
            "start": round(item.start_seconds, 3),
            "end": round(item.end_seconds, 3),
            "duration": round(item.duration_seconds, 3),
            "cache_hit": item.cache_hit,
        }
        for item in metrics.timeline
        if item.stage in {"jd_trim", "flash_primary", "flash_repair", "pro_primary", "pro_repair"}
    ]
    return {
        "boss_payload_import_seconds": round(import_seconds, 3),
        "total_elapsed_seconds": round(metrics.timing.total_elapsed_seconds, 3),
        "time_to_first_result_seconds": round(metrics.timing.time_to_first_result_seconds, 3),
        "local_seconds": round(metrics.timing.local_seconds, 3),
        "flash_stage_seconds": round(metrics.timing.flash_seconds, 3),
        "pro_stage_seconds": round(metrics.timing.pro_seconds, 3),
        "local_filtered": metrics.local_filtered,
        "jd_parse_calls": metrics.jd_parse_calls,
        "flash_calls": metrics.flash_provider_calls,
        "pro_calls": metrics.pro_provider_calls,
        "repair_calls": metrics.repair_calls,
        "cache_hits": metrics.cache_hits,
        "cache_misses": metrics.cache_misses,
        "duplicate_jobs": metrics.duplicate_jobs,
        "timeline": provider_timeline,
    }


def main() -> int:
    config = load_config()
    if not config.has_api_key:
        print(json.dumps({"status": "skipped", "reason": "provider_not_configured"}))
        return 0
    imported_started = perf_counter()
    jobs = discovery_items_to_batch_inputs(_public_boss_jobs())
    import_seconds = perf_counter() - imported_started
    client = DeepSeekLLMClient(config)
    caches = ({}, {}, {}, {}, {}, {})
    pipeline = FastScreeningPipeline(
        LocalPreScreenService(),
        FastScreeningService(client),
        MatchingService(client),
        local_cache=caches[0],
        fast_cache=caches[1],
        deep_cache=caches[2],
        trimmed_jd_cache=caches[3],
        compact_summary_cache=caches[4],
        job_profile_cache=caches[5],
    )
    cold = pipeline.process(_candidate(), "5" * 64, jobs)
    warm = pipeline.process(_candidate(), "5" * 64, jobs)
    print(json.dumps({"status": "success", "cold": _summary(cold, import_seconds), "warm": _summary(warm, import_seconds)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
