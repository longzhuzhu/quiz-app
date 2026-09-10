"""AI 解析更新：缓存口径、结构校验、纠正重试、CAS 与 force。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import ai_service  # noqa: E402
from app.services.exam_service import (  # noqa: E402
    DEFAULT_EXPLANATION_PERSONA,
    build_explanation_system_prompt,
)


def _question(**overrides):
    question = MagicMock(name="question")
    question.options = [
        {"key": "A", "text": "opt a"},
        {"key": "B", "text": "opt b"},
        {"key": "C", "text": "opt c"},
    ]
    question.content = "Which control is MOST effective before data leaves the company?"
    question.correct_answer = "B"
    question.bank = None
    question.explanation = None
    question.explanation_zh = None
    for key, value in overrides.items():
        setattr(question, key, value)
    return question


def _valid_result(**overrides) -> dict:
    result = {
        "stem_breakdown": {
            "qualifier": "MOST",
            "role": "负责上线分析平台的隐私工程师",
            "scenario": "公司准备把用户行为日志接入第三方分析服务",
            "constraint": "处理必须在数据离开公司边界前完成",
            "asked": "四种做法里哪一种最能降低再识别风险（MOST 问最优而非可行）",
        },
        "explanation": "De-identification must happen before data leaves the company boundary.",
        "explanation_zh": (
            "在数据离开公司边界前做去标识化，能降低再识别风险。"
            "仅加密或仅限制传输范围都无法覆盖存储侧暴露。"
        ),
        "judged_answer": "B",
        "distractors": [
            {"key": "A", "type": "范围过窄", "reason": "只覆盖传输环节，没处理存储侧"},
            {"key": "C", "type": "术语混淆", "reason": "把加密当成去标识化"},
        ],
    }
    result.update(overrides)
    return result


def _patch_calls(monkeypatch, responses):
    captured = {"calls": 0, "messages": []}

    def fake_call_ai_api(messages, db, scene="default", timeout=60.0):
        captured["calls"] += 1
        captured["messages"].append(messages)
        captured["scene"] = scene
        item = responses[captured["calls"] - 1]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(ai_service, "call_ai_api", fake_call_ai_api)
    return captured


# ─── 缓存口径 ────────────────────────────────────────────────────────


def test_has_question_explanation_requires_chinese():
    assert ai_service.has_question_explanation(_question(explanation_zh="中文解析")) is True
    assert ai_service.has_question_explanation(_question(explanation="English only")) is False
    assert ai_service.has_question_explanation(_question(explanation="English", explanation_zh="")) is False
    assert ai_service.has_question_explanation(_question(explanation="English", explanation_zh="中文")) is True


# ─── 结构校验 ────────────────────────────────────────────────────────


def test_validate_structured_explanation_accepts_valid_sample():
    assert ai_service.validate_structured_explanation(_valid_result(), _question()) == []


def test_validate_structured_explanation_rejects_missing_stem_breakdown():
    result = _valid_result()
    result.pop("stem_breakdown")
    errors = ai_service.validate_structured_explanation(result, _question())
    assert any("stem_breakdown" in item or "题干拆解" in item for item in errors)


def test_validate_structured_explanation_rejects_missing_wrong_option():
    result = _valid_result(distractors=[{"key": "A", "type": "范围过窄", "reason": "只覆盖传输环节，没处理存储侧"}])
    errors = ai_service.validate_structured_explanation(result, _question())
    assert any("未覆盖" in item and "C" in item for item in errors)


def test_validate_structured_explanation_rejects_correct_answer_in_distractors():
    result = _valid_result(
        distractors=[
            {"key": "A", "type": "范围过窄", "reason": "只覆盖传输环节，没处理存储侧"},
            {"key": "B", "type": "术语混淆", "reason": "把加密当成去标识化"},
            {"key": "C", "type": "术语混淆", "reason": "把加密当成去标识化"},
        ]
    )
    errors = ai_service.validate_structured_explanation(result, _question())
    assert any("正确答案" in item and "B" in item for item in errors)


def test_validate_structured_explanation_rejects_illegal_type():
    result = _valid_result(
        distractors=[
            {"key": "A", "type": "随便写的类型", "reason": "只覆盖传输环节，没处理存储侧"},
            {"key": "C", "type": "术语混淆", "reason": "把加密当成去标识化"},
        ]
    )
    errors = ai_service.validate_structured_explanation(result, _question())
    assert any("type" in item for item in errors)


@pytest.mark.parametrize("reason", ["该选项不正确", "该选项错误", "不正确", "不对"])
def test_validate_structured_explanation_rejects_generic_reason(reason):
    result = _valid_result(
        distractors=[
            {"key": "A", "type": "范围过窄", "reason": reason},
            {"key": "C", "type": "术语混淆", "reason": "把加密当成去标识化"},
        ]
    )
    errors = ai_service.validate_structured_explanation(result, _question())
    assert any("空泛" in item for item in errors)


def test_validate_structured_explanation_rejects_single_conclusion_sentence():
    result = _valid_result(explanation_zh="正确答案是 B")
    errors = ai_service.validate_structured_explanation(result, _question())
    assert any("两句" in item for item in errors)


def test_validate_structured_explanation_rejects_empty_qualifier_when_stem_has_most():
    result = _valid_result()
    result["stem_breakdown"]["qualifier"] = ""
    errors = ai_service.validate_structured_explanation(result, _question())
    assert any("qualifier" in item for item in errors)


def test_validate_structured_explanation_allows_empty_qualifier_without_stem_word():
    question = _question(content="What should the engineer do before data leaves?")
    result = _valid_result()
    result["stem_breakdown"]["qualifier"] = ""
    assert ai_service.validate_structured_explanation(result, question) == []


# ─── 重试与落库 ──────────────────────────────────────────────────────


def test_explain_question_retries_once_then_commits(monkeypatch):
    invalid = json.dumps({"explanation": "English", "explanation_zh": "中文解析"}, ensure_ascii=False)
    valid = json.dumps(_valid_result(), ensure_ascii=False)
    captured = _patch_calls(monkeypatch, [invalid, valid])
    db = MagicMock(name="db")
    question = _question()

    payload = ai_service.explain_question(db, question)

    assert captured["calls"] == 2
    assert "校验错误" in captured["messages"][1][-1]["content"]
    assert ai_service.SECTION_STEM_BREAKDOWN in payload["explanation_zh"]
    db.commit.assert_called_once()


def test_explain_question_second_failure_does_not_commit(monkeypatch):
    invalid = json.dumps({"explanation": "English", "explanation_zh": "中文解析"}, ensure_ascii=False)
    captured = _patch_calls(monkeypatch, [invalid, invalid])
    db = MagicMock(name="db")
    question = _question()

    with pytest.raises(ValueError, match="未通过校验"):
        ai_service.explain_question(db, question)

    assert captured["calls"] == 2
    assert question.explanation is None
    assert question.explanation_zh is None
    db.commit.assert_not_called()


def test_explain_question_valid_first_response_calls_model_once(monkeypatch):
    captured = _patch_calls(monkeypatch, [json.dumps(_valid_result(), ensure_ascii=False)])
    db = MagicMock(name="db")

    ai_service.explain_question(db, _question())

    assert captured["calls"] == 1
    db.commit.assert_called_once()


def test_explain_question_timeout_does_not_use_correction_retry(monkeypatch):
    captured = _patch_calls(monkeypatch, [httpx.TimeoutException("timeout")])
    db = MagicMock(name="db")

    with pytest.raises(httpx.TimeoutException):
        ai_service.explain_question(db, _question())

    assert captured["calls"] == 1
    db.commit.assert_not_called()


def test_explain_question_missing_key_does_not_use_correction_retry(monkeypatch):
    captured = _patch_calls(monkeypatch, [ValueError("AI API Key 未配置，请在管理后台设置")])
    db = MagicMock(name="db")

    with pytest.raises(ValueError, match="AI API Key"):
        ai_service.explain_question(db, _question())

    assert captured["calls"] == 1
    db.commit.assert_not_called()


def test_explain_question_force_false_does_not_overwrite_after_refresh(monkeypatch):
    captured = _patch_calls(monkeypatch, [json.dumps(_valid_result(), ensure_ascii=False)])
    db = MagicMock(name="db")
    question = _question()

    def fake_refresh(target):
        target.explanation = "old english"
        target.explanation_zh = "已有中文解析"

    db.refresh.side_effect = fake_refresh

    payload = ai_service.explain_question(db, question, force=False)

    assert captured["calls"] == 1
    assert payload["explanation_zh"] == "已有中文解析"
    assert question.explanation_zh == "已有中文解析"
    db.commit.assert_not_called()


def test_explain_question_force_true_overwrites_existing(monkeypatch):
    captured = _patch_calls(monkeypatch, [json.dumps(_valid_result(), ensure_ascii=False)])
    db = MagicMock(name="db")
    question = _question(explanation="old english", explanation_zh="已有中文解析")

    payload = ai_service.explain_question(db, question, force=True)

    assert captured["calls"] == 1
    assert payload["explanation_zh"] != "已有中文解析"
    assert ai_service.SECTION_STEM_BREAKDOWN in question.explanation_zh
    db.refresh.assert_not_called()
    db.commit.assert_called_once()


def test_explain_question_rejects_legacy_two_key_persist(monkeypatch):
    captured = _patch_calls(
        monkeypatch,
        [json.dumps({"explanation": "English", "explanation_zh": "中文解析"}, ensure_ascii=False)] * 2,
    )
    db = MagicMock(name="db")
    question = _question()

    with pytest.raises(ValueError, match="未通过校验"):
        ai_service.explain_question(db, question)

    assert captured["calls"] == 2
    assert question.explanation is None
    assert question.explanation_zh is None
    db.commit.assert_not_called()


def test_explain_question_uses_platform_contract_even_with_custom_persona(monkeypatch):
    question = _question()
    exam = MagicMock()
    exam.ai_profile = {"explanation_system_prompt": "你是 CIPP 辅导专家。"}
    bank = MagicMock()
    bank.exam = exam
    question.bank = bank
    captured = _patch_calls(monkeypatch, [json.dumps(_valid_result(), ensure_ascii=False)])

    ai_service.explain_question(MagicMock(name="db"), question)

    system_prompt = captured["messages"][0][0]["content"]
    assert system_prompt == build_explanation_system_prompt("你是 CIPP 辅导专家。")
    assert system_prompt != DEFAULT_EXPLANATION_PERSONA
    assert "stem_breakdown" in system_prompt
    assert "judged_answer" in system_prompt


def test_validate_structured_explanation_requires_judged_answer():
    result = _valid_result()
    result.pop("judged_answer")
    errors = ai_service.validate_structured_explanation(result, _question())
    assert any("judged_answer" in item for item in errors)


def test_validate_structured_explanation_rejects_unknown_judged_key():
    errors = ai_service.validate_structured_explanation(
        _valid_result(judged_answer="Z"),
        _question(),
    )
    assert any("judged_answer" in item and "Z" in item for item in errors)


def test_validate_structured_explanation_strips_trailing_dot_on_judged_answer():
    assert ai_service.validate_structured_explanation(
        _valid_result(judged_answer="B."),
        _question(),
    ) == []


def test_validate_structured_explanation_uses_judged_answer_not_db_correct():
    """模型认定 B、库内 C 时，干扰项覆盖 A/C 即可。"""
    question = _question(correct_answer="C")
    result = _valid_result(
        judged_answer="B",
        distractors=[
            {"key": "A", "type": "范围过窄", "reason": "只覆盖传输环节，没处理存储侧"},
            {"key": "C", "type": "术语混淆", "reason": "把加密当成去标识化"},
        ],
    )
    assert ai_service.validate_structured_explanation(result, question) == []


def _conflict_result() -> dict:
    return _valid_result(
        judged_answer="C",
        distractors=[
            {"key": "A", "type": "范围过窄", "reason": "只覆盖传输环节，没处理存储侧"},
            {"key": "B", "type": "术语混淆", "reason": "把加密当成去标识化"},
        ],
    )


def test_explain_question_conflict_does_not_retry_or_rewrite(monkeypatch):
    captured = _patch_calls(monkeypatch, [json.dumps(_conflict_result(), ensure_ascii=False)])
    db = MagicMock(name="db")
    question = _question(correct_answer="B")

    payload = ai_service.explain_question(db, question)

    assert captured["calls"] == 1
    assert payload["explanation_zh"].startswith(ai_service.SECTION_ANSWER_CONFLICT)
    assert "题库答案：B" in payload["explanation_zh"]
    assert "AI 认定：C" in payload["explanation_zh"]
    assert ai_service.SECTION_STEM_BREAKDOWN in payload["explanation_zh"]
    assert ai_service.SECTION_DISTRACTORS in payload["explanation_zh"]
    assert "把加密当成去标识化" in payload["explanation_zh"]
    db.commit.assert_called_once()


def test_explain_question_matching_answers_have_no_conflict_section(monkeypatch):
    captured = _patch_calls(monkeypatch, [json.dumps(_valid_result(), ensure_ascii=False)])
    payload = ai_service.explain_question(MagicMock(name="db"), _question(correct_answer="B"))

    assert captured["calls"] == 1
    assert ai_service.SECTION_ANSWER_CONFLICT not in payload["explanation_zh"]


def test_explain_question_missing_judged_answer_retries_once(monkeypatch):
    missing = _valid_result()
    missing.pop("judged_answer")
    captured = _patch_calls(
        monkeypatch,
        [json.dumps(missing, ensure_ascii=False), json.dumps(_valid_result(), ensure_ascii=False)],
    )
    db = MagicMock(name="db")

    payload = ai_service.explain_question(db, _question())

    assert captured["calls"] == 2
    retry_content = captured["messages"][1][-1]["content"]
    assert "校验错误" in retry_content
    assert "正确答案：" not in retry_content
    for messages in captured["messages"]:
        for message in messages:
            if message["role"] == "user":
                assert "正确答案：" not in message["content"]
    assert ai_service.SECTION_STEM_BREAKDOWN in payload["explanation_zh"]
    db.commit.assert_called_once()
