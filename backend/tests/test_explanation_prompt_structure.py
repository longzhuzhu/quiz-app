"""AI 解析 prompt 结构化改造的单元测试。

覆盖路径：
    TC-1  新默认 prompt 包含 stem_breakdown / distractors 契约、限定词与干扰项枚举。
    TC-2  compose_explanation_zh 把结构化字段组装成固定顺序的分段文本。
    TC-3  只有 stem_breakdown 或只有 distractors 时也能组装，缺失字段被跳过。
    TC-4  旧的两键返回结构原样透传（自定义 prompt 向后兼容）。
    TC-5  explain_question 写入组装后的文本，且缺 explanation 键不抛 KeyError。
    TC-6  两个字段都为空时抛 ValueError，由路由层转成 500，不写入空解析。
    TC-7  migration 004 的旧 prompt 字面量与 migration 003 实际写入的值一致
          （不一致会让 UPDATE 静默匹配不到任何行）。
    TC-8  migration 004 的新 prompt 字面量与 exam_service 当前常量一致
          （改 prompt 必须同步补迁移，否则存量考试项目取不到新 prompt）。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import ai_service  # noqa: E402
from app.services.exam_service import (  # noqa: E402
    CIPT_EXPLANATION_SYSTEM_PROMPT,
    DEFAULT_EXPLANATION_SYSTEM_PROMPT,
    EXPLANATION_DISTRACTOR_TYPES,
    EXPLANATION_STEM_QUALIFIERS,
)


def _load_migration(filename: str):
    """按文件路径加载 alembic 版本文件（目录不是 package，不能直接 import）。"""
    path = BACKEND_ROOT / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location(f"_migration_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _structured_result() -> dict:
    return {
        "stem_breakdown": {
            "qualifier": "MOST",
            "role": "负责上线分析平台的隐私工程师",
            "scenario": "公司准备把用户行为日志接入第三方分析服务",
            "constraint": "处理必须在数据离开公司边界前完成",
            "asked": "四种做法里哪一种最能降低再识别风险（MOST 问最优而非可行）",
        },
        "explanation": "The correct answer is B because ...",
        "explanation_zh": "B 正确，因为在数据离开边界前做去标识化 ...",
        "distractors": [
            {"key": "A", "type": "范围过窄", "reason": "只覆盖传输环节，没处理存储侧"},
            {"key": "C", "type": "术语混淆", "reason": "把加密当成去标识化"},
        ],
    }


# ─── TC-1 ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "prompt",
    [DEFAULT_EXPLANATION_SYSTEM_PROMPT, CIPT_EXPLANATION_SYSTEM_PROMPT],
    ids=["default", "cipt"],
)
def test_explanation_prompt_declares_structured_contract(prompt):
    """两个默认 prompt 都必须声明结构化字段、限定词清单和干扰项枚举。"""
    for key in ("stem_breakdown", "distractors", "explanation_zh", "qualifier", "asked"):
        assert key in prompt, f"prompt 缺少 {key} 契约说明"

    for qualifier in EXPLANATION_STEM_QUALIFIERS:
        assert qualifier in prompt, f"prompt 未列出题干限定词 {qualifier}"

    for distractor_type in EXPLANATION_DISTRACTOR_TYPES:
        assert distractor_type in prompt, f"prompt 未列出干扰项类型 {distractor_type}"

    assert "只返回 JSON" in prompt


def test_cipt_prompt_keeps_exam_specific_persona():
    assert CIPT_EXPLANATION_SYSTEM_PROMPT.startswith("你是一位 CIPT")
    assert DEFAULT_EXPLANATION_SYSTEM_PROMPT.startswith("你是专业考试辅导专家。")


# ─── TC-2 ────────────────────────────────────────────────────────────


def test_compose_explanation_zh_renders_sections_in_fixed_order():
    """题干拆解 → 知识点解析 → 干扰项分析，版式由服务端固定。"""
    composed = ai_service.compose_explanation_zh(_structured_result())

    assert composed.index(ai_service.SECTION_STEM_BREAKDOWN) == 0
    assert (
        composed.index(ai_service.SECTION_STEM_BREAKDOWN)
        < composed.index(ai_service.SECTION_ANSWER_ANALYSIS)
        < composed.index(ai_service.SECTION_DISTRACTORS)
    )

    # 题干拆解的 5 个标签按 STEM_BREAKDOWN_LABELS 顺序出现
    label_positions = [composed.index(f"{label}：") for _, label in ai_service.STEM_BREAKDOWN_LABELS]
    assert label_positions == sorted(label_positions)

    assert "限定词：MOST" in composed
    assert "A（范围过窄）：只覆盖传输环节，没处理存储侧" in composed
    assert "C（术语混淆）：把加密当成去标识化" in composed
    # 英文解析不进中文字段
    assert "The correct answer is B" not in composed


# ─── TC-3 ────────────────────────────────────────────────────────────


def test_compose_explanation_zh_skips_blank_breakdown_fields():
    """空字符串 / 缺失的拆解字段不产生空行。"""
    composed = ai_service.compose_explanation_zh(
        {
            "stem_breakdown": {"qualifier": "", "role": "数据保护官", "scenario": None, "asked": "问什么"},
            "explanation_zh": "知识点",
        }
    )

    assert "限定词" not in composed
    assert "场景" not in composed
    assert "角色：数据保护官" in composed
    assert "问的是什么：问什么" in composed
    assert "\n\n\n" not in composed


def test_compose_explanation_zh_with_only_distractors():
    composed = ai_service.compose_explanation_zh(
        {
            "explanation_zh": "知识点",
            "distractors": [{"key": "D", "type": "无关干扰", "reason": "与题干无关"}],
        }
    )

    assert ai_service.SECTION_STEM_BREAKDOWN not in composed
    assert ai_service.SECTION_ANSWER_ANALYSIS in composed
    assert "D（无关干扰）：与题干无关" in composed


def test_compose_explanation_zh_tolerates_malformed_structures():
    """LLM 返回类型不对时降级为纯文本，不抛异常。"""
    composed = ai_service.compose_explanation_zh(
        {
            "stem_breakdown": "不是 dict",
            "distractors": ["不是 dict", {}, {"key": "B"}],
            "explanation_zh": "知识点",
        }
    )

    assert ai_service.SECTION_STEM_BREAKDOWN not in composed
    assert "B" in composed
    assert "知识点" in composed


def test_compose_explanation_zh_coerces_numeric_option_key():
    """LLM 把选项 key 返回成数字时不能丢掉这条干扰项。"""
    composed = ai_service.compose_explanation_zh(
        {
            "explanation_zh": "知识点",
            "distractors": [
                {"key": 2, "type": "范围过宽", "reason": "做了题干没要求的事"},
                {"key": True, "type": "", "reason": ""},
            ],
        }
    )

    assert "2（范围过宽）：做了题干没要求的事" in composed
    assert "True" not in composed


# ─── TC-4 ────────────────────────────────────────────────────────────


def test_compose_explanation_zh_passes_through_legacy_two_key_shape():
    """自定义 prompt 仍返回旧的两键结构时，行为与改动前完全一致。"""
    legacy = {"explanation": "English", "explanation_zh": "中文解析"}

    composed = ai_service.compose_explanation_zh(legacy)

    assert composed == "中文解析"
    assert ai_service.SECTION_ANSWER_ANALYSIS not in composed


# ─── TC-5 / TC-6 ─────────────────────────────────────────────────────


@pytest.fixture
def fake_question():
    question = MagicMock(name="question")
    question.options = [{"key": "A", "text": "opt a"}, {"key": "B", "text": "opt b"}]
    question.content = "stem"
    question.correct_answer = "B"
    question.bank = None
    question.explanation = None
    question.explanation_zh = None
    return question


def _patch_ai_response(monkeypatch, payload: str) -> dict:
    captured: dict = {}

    def fake_call_ai_api(messages, db, scene="default", timeout=60.0):
        captured["messages"] = messages
        captured["scene"] = scene
        return payload

    monkeypatch.setattr(ai_service, "call_ai_api", fake_call_ai_api)
    return captured


def test_explain_question_persists_composed_text(monkeypatch, fake_question):
    import json

    captured = _patch_ai_response(monkeypatch, json.dumps(_structured_result(), ensure_ascii=False))
    db = MagicMock(name="db")

    payload = ai_service.explain_question(db, fake_question)

    assert captured["scene"] == "explain"
    assert fake_question.explanation == "The correct answer is B because ..."
    assert ai_service.SECTION_STEM_BREAKDOWN in fake_question.explanation_zh
    assert ai_service.SECTION_DISTRACTORS in fake_question.explanation_zh
    assert payload["explanation_zh"] == fake_question.explanation_zh
    db.commit.assert_called_once()


def test_explain_question_without_explanation_key_does_not_raise(monkeypatch, fake_question):
    """LLM 漏返 explanation 键时不再 KeyError，中文解析仍然落库。"""
    _patch_ai_response(
        monkeypatch,
        '{"explanation_zh": "中文解析", "distractors": [{"key": "A", "type": "范围过窄", "reason": "太窄"}]}',
    )

    ai_service.explain_question(MagicMock(name="db"), fake_question)

    assert fake_question.explanation is None
    assert "A（范围过窄）：太窄" in fake_question.explanation_zh


def test_explain_question_raises_when_result_is_empty(monkeypatch, fake_question):
    """两个字段都空时必须报错，否则会缓存一条空解析且永远不再重算。"""
    _patch_ai_response(monkeypatch, '{"explanation": "  ", "explanation_zh": ""}')
    db = MagicMock(name="db")

    with pytest.raises(ValueError):
        ai_service.explain_question(db, fake_question)

    assert fake_question.explanation is None
    assert fake_question.explanation_zh is None
    db.commit.assert_not_called()


# ─── TC-7 / TC-8 ─────────────────────────────────────────────────────


def test_migration_004_old_prompt_matches_what_migration_003_wrote():
    """004 的旧 CIPT prompt 必须与 003 写入 DB 的值逐字节相等。

    不相等则 `WHERE ai_profile->>'explanation_system_prompt' = :old_prompt`
    匹配不到任何行，迁移静默无效，存量考试项目仍在用旧 prompt。
    """
    migration_003 = _load_migration("003_user_owned_exams.py")
    migration_004 = _load_migration("004_structured_explanation_prompt.py")

    assert (
        migration_004.OLD_CIPT_EXPLANATION_PROMPT
        == migration_003.CIPT_AI_PROFILE["explanation_system_prompt"]
    )


def test_migration_004_new_prompt_matches_current_service_constants():
    """004 的新 prompt 必须等于 exam_service 当前常量。

    失败说明有人改了 prompt 常量但没补迁移：新建的考试项目会用新 prompt，
    存量项目仍停在旧 prompt，两边行为分叉。修法是新增一个迁移把存量行升级。
    """
    migration_004 = _load_migration("004_structured_explanation_prompt.py")

    assert migration_004.NEW_DEFAULT_EXPLANATION_PROMPT == DEFAULT_EXPLANATION_SYSTEM_PROMPT
    assert migration_004.NEW_CIPT_EXPLANATION_PROMPT == CIPT_EXPLANATION_SYSTEM_PROMPT


def test_migration_004_revision_chain():
    migration_004 = _load_migration("004_structured_explanation_prompt.py")

    assert migration_004.revision == "004"
    assert migration_004.down_revision == "003"


class _RecordingBind:
    """记录 execute 参数，用于在没有 PostgreSQL 的环境下验证迁移的替换映射。"""

    def __init__(self):
        self.calls: list[dict] = []

    def execute(self, statement, params):
        self.calls.append({"sql": str(statement), "params": params})


def _run_migration_direction(monkeypatch, direction: str) -> _RecordingBind:
    migration_004 = _load_migration("004_structured_explanation_prompt.py")
    bind = _RecordingBind()
    monkeypatch.setattr(migration_004.op, "get_bind", lambda: bind)

    getattr(migration_004, direction)()
    return bind


def test_migration_004_upgrade_maps_old_prompts_to_new(monkeypatch):
    """upgrade 必须 old -> new，且只按 explanation_system_prompt 精确匹配。"""
    migration_004 = _load_migration("004_structured_explanation_prompt.py")
    bind = _run_migration_direction(monkeypatch, "upgrade")

    assert len(bind.calls) == 2
    for call in bind.calls:
        assert "explanation_system_prompt" in call["sql"]
        assert "jsonb_set" in call["sql"]

    swaps = {(call["params"]["old_prompt"], call["params"]["new_prompt"]) for call in bind.calls}
    assert swaps == {
        (migration_004.OLD_CIPT_EXPLANATION_PROMPT, migration_004.NEW_CIPT_EXPLANATION_PROMPT),
        (migration_004.OLD_DEFAULT_EXPLANATION_PROMPT, migration_004.NEW_DEFAULT_EXPLANATION_PROMPT),
    }


def test_migration_004_downgrade_is_exact_inverse(monkeypatch):
    migration_004 = _load_migration("004_structured_explanation_prompt.py")
    upgrade_swaps = {
        (call["params"]["old_prompt"], call["params"]["new_prompt"])
        for call in _run_migration_direction(monkeypatch, "upgrade").calls
    }
    downgrade_swaps = {
        (call["params"]["new_prompt"], call["params"]["old_prompt"])
        for call in _run_migration_direction(monkeypatch, "downgrade").calls
    }

    assert upgrade_swaps == downgrade_swaps
    # 反向防御：persona 不能在替换过程中被串到另一个 prompt 上
    assert migration_004.NEW_CIPT_EXPLANATION_PROMPT.startswith("你是一位 CIPT")
    assert migration_004.NEW_DEFAULT_EXPLANATION_PROMPT.startswith("你是专业考试辅导专家。")
