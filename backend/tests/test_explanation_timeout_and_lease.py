"""解析超时配置与任务租约契约。

覆盖路径：
    TC-1  AI_EXPLANATION_TIMEOUT_SECONDS 默认为 120，且必须是正数。
    TC-2  generate_structured_explanation 把 timeout 透传给每次 call_ai_api。
    TC-3  输出格式不合格触发纠正重试时，第二次调用沿用同一 timeout。
    TC-4  解析任务租约长于「超时 × 2」的最坏耗时，否则会被 recover_stale_jobs 误判中断。
    TC-5  解析路径不调用 heartbeat_job，租约不会被续回默认值。
    TC-6  连接池上限覆盖 worker 线程数与解析槽位数之和。
"""

from __future__ import annotations

import inspect
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core import config as config_module  # noqa: E402
from app.core import database as database_module  # noqa: E402
from app.services import ai_service, job_service  # noqa: E402
from app.workers import job_worker  # noqa: E402


# ─── TC-1 ────────────────────────────────────────────────────────────


def test_explanation_timeout_defaults_to_120_seconds():
    """解析超时默认 120s；提升到该值是为消除频繁的 60s 超时失败。"""
    field = config_module.Settings.model_fields["AI_EXPLANATION_TIMEOUT_SECONDS"]
    assert field.default == 120.0


def test_explanation_timeout_must_be_positive():
    """非正超时被配置校验拒绝，避免退化成无超时或立即超时。"""
    with pytest.raises(Exception):
        config_module.Settings(AI_EXPLANATION_TIMEOUT_SECONDS=0)


# ─── TC-2 / TC-3 ─────────────────────────────────────────────────────


def _question_stub() -> SimpleNamespace:
    return SimpleNamespace(
        question_type="single",
        content="Which control is MOST effective?",
        options=[{"key": key, "text": f"Option {key}"} for key in "ABCD"],
    )


def _valid_payload() -> str:
    """满足 validate_structured_explanation 的最小合法载荷。

    题干含 MOST，因此 qualifier 必填；知识点解析需至少两句有实质信息的完整说明。
    """
    import json

    return json.dumps({
        "judged_answer": "D",
        "stem_breakdown": {
            "qualifier": "MOST", "role": "隐私工程师", "scenario": "比较数据保护措施",
            "constraint": "选择最有效的措施", "asked": "哪项措施最有效",
        },
        "explanation": "The measure reduces exposure across the whole lifecycle.",
        "explanation_zh": "该措施在整个数据生命周期内减少暴露面。它同时覆盖了存储和传输两个环节。",
        "distractors": [
            {"key": key, "type": "范围过窄", "reason": "只覆盖数据处理的单个环节，无法满足题干整体限制"} for key in "ABC"
        ],
    }, ensure_ascii=False)


def test_structured_explanation_passes_timeout_to_every_call(monkeypatch):
    """timeout 必须显式下传；不在 call_ai_api 内部按 scene 兜底，避免破坏其既有默认契约。"""
    captured: list = []

    def fake_call(messages, db, **kwargs):
        captured.append(kwargs.get("timeout"))
        return _valid_payload()

    monkeypatch.setattr(ai_service, "call_ai_api", fake_call)

    ai_service.generate_structured_explanation(
        _question_stub(), persona="persona", ai_config={}, reasoning_effort=None, timeout=120.0,
    )

    assert captured == [120.0]


def test_correction_retry_reuses_same_timeout(monkeypatch):
    """首次输出不合格时的纠正重试沿用同一超时，最坏耗时为该值的两倍。"""
    captured: list = []
    responses = iter(["不符合格式的输出", _valid_payload()])

    def fake_call(messages, db, **kwargs):
        captured.append(kwargs.get("timeout"))
        return next(responses)

    monkeypatch.setattr(ai_service, "call_ai_api", fake_call)

    ai_service.generate_structured_explanation(
        _question_stub(), persona="persona", ai_config={}, reasoning_effort=None, timeout=120.0,
    )

    assert captured == [120.0, 120.0]


def test_timeout_is_required_keyword(monkeypatch):
    """超时是必传关键字参数，防止新增调用点静默退回 60s 默认值。"""
    parameters = inspect.signature(ai_service.generate_structured_explanation).parameters
    assert parameters["timeout"].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters["timeout"].default is inspect.Parameter.empty


def test_execution_path_uses_settings_timeout():
    """execute_explanation 必须把配置值传给生成函数，而不是依赖其内部默认。"""
    source = (BACKEND_ROOT / "app" / "services" / "explanation_service.py").read_text(encoding="utf-8")
    assert re.search(r"timeout=settings\.AI_EXPLANATION_TIMEOUT_SECONDS", source), (
        "explanation_service.execute_explanation 未使用 settings.AI_EXPLANATION_TIMEOUT_SECONDS"
    )


# ─── TC-4 / TC-5 ─────────────────────────────────────────────────────


def test_explanation_lease_covers_worst_case_duration():
    """解析任务执行期间不续约，租约必须覆盖「超时 × 2」的最坏耗时。"""
    worst_case = 2 * config_module.Settings.model_fields["AI_EXPLANATION_TIMEOUT_SECONDS"].default
    assert job_service.EXPLANATION_JOB_LEASE_SECONDS > worst_case, (
        f"解析租约 {job_service.EXPLANATION_JOB_LEASE_SECONDS}s 未覆盖最坏耗时 {worst_case}s，"
        "任务会被 recover_stale_jobs 误判为执行已中断"
    )


def test_explanation_lease_differs_from_default():
    """解析租约与通用租约分离，调大超时不应连带放宽其他任务类型的回收时效。"""
    assert job_service.EXPLANATION_JOB_LEASE_SECONDS > job_service.DEFAULT_JOB_LEASE_SECONDS


def test_explanation_execution_does_not_heartbeat():
    """解析执行路径不调用 heartbeat_job；若调用会把租约续回默认 180s，抵消延长。"""
    source = (BACKEND_ROOT / "app" / "services" / "explanation_service.py").read_text(encoding="utf-8")
    assert "heartbeat_job" not in source


# ─── TC-6 ────────────────────────────────────────────────────────────


def test_pool_capacity_covers_worker_threads_and_slots():
    """每个解析任务持有会话连接与 advisory lock 连接，池上限需覆盖两者之和。"""
    capacity = database_module.engine.pool.size() + database_module.engine.pool._max_overflow
    required = job_worker.DEFAULT_CONCURRENCY + config_module.Settings.model_fields["AI_EXPLANATION_CONCURRENCY"].default
    assert capacity >= required, f"连接池上限 {capacity} 不足以支撑 {required} 条并发解析连接"


def test_concurrency_defaults_support_ten_parallel_explanations():
    """解析槽位与 worker 线程数均默认为 10，任一偏低都无法跑满 10 并发。"""
    assert config_module.Settings.model_fields["AI_EXPLANATION_CONCURRENCY"].default == 10
    assert job_worker.DEFAULT_CONCURRENCY == 10
