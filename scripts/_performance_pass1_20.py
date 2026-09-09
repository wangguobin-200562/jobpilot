"""Fixed 20-job provider benchmark for screening scalability checks."""

from __future__ import annotations

from collections import Counter
import json

from jobpilot.config import load_config
from jobpilot.llm import DeepSeekLLMClient
from jobpilot.models import BatchJobInput
from jobpilot.services import FastScreeningPipeline, FastScreeningService, LocalPreScreenService, MatchingService
from _performance_pass1_real_5 import _candidate


def _job(index: int, group: str) -> BatchJobInput:
    variants = {
        "high": "负责 Python 大模型应用、Agent 工作流、RAG、FastAPI 接口和效果评估；要求熟悉 LLM API、Git、SQL，具备项目测试与文档能力。",
        "medium": "负责 Python 数据处理、SQL 指标分析、后端接口与自动化脚本；FastAPI、Docker 和大模型应用经验为加分项，要求良好沟通能力。",
        "low": "协助 AI 产品需求整理、用户反馈分析、运营数据复盘和功能验收；要求理解大模型产品、会使用 Excel 或 SQL，并具备跨团队沟通能力。",
        "unrelated": "资深 Java 微服务架构岗位，明确要求五年以上经验，精通 Spring Cloud、JVM 调优和高并发架构，承担团队技术负责人职责。",
    }
    text = f"固定基准岗位 {index}。岗位职责与任职要求：{variants[group]} 本岗位用于 JobPilot 固定性能与分类回归测试。"
    return BatchJobInput(
        index=index,
        company=f"固定虚构公司{index}",
        job_title=f"{group} 基准岗位 {index}",
        jd_text=text,
        raw_block=text,
        source_url=f"https://example.com/performance-job-{index}",
    )


def main() -> int:
    config = load_config()
    if not config.has_api_key:
        print(json.dumps({"status": "skipped", "reason": "provider_not_configured"}))
        return 0
    groups = ["high"] * 5 + ["medium"] * 5 + ["low"] * 5 + ["unrelated"] * 5
    jobs = [_job(index, group) for index, group in enumerate(groups, 1)]
    client = DeepSeekLLMClient(config)
    result = FastScreeningPipeline(
        LocalPreScreenService(), FastScreeningService(client), MatchingService(client)
    ).process(_candidate(), "2" * 64, jobs)
    tiers = Counter(item.screening_tier.value for item in result.items)
    metrics = result.metrics
    safe = {
        "status": "success",
        "total_jobs": metrics.total_jobs,
        "local_filtered": metrics.local_filtered,
        "jd_parse_calls": metrics.jd_parse_calls,
        "flash_calls": metrics.flash_provider_calls,
        "pro_calls": metrics.pro_provider_calls,
        "repair_calls": metrics.repair_calls,
        "pro_ratio": round(metrics.pro_provider_calls / metrics.total_jobs, 3),
        "time_to_first_result": round(metrics.timing.time_to_first_result_seconds, 3),
        "time_to_final_result": round(metrics.timing.total_elapsed_seconds, 3),
        "tier_counts": dict(tiers),
    }
    print(json.dumps(safe, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
