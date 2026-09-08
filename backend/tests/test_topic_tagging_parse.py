"""考点打标响应解析的单元测试

覆盖 topic_tagging_service.parse_tagging_response 的契约：
- 正常解析多个编码
- 空数组表示 AI 判不准，该题落入未分类
- 不在考点树内的编码被丢弃，不污染数据
- 响应被 markdown 代码围栏包裹时仍可解析
- 越界或缺失的题号不产生结果
- 整体不可解析时抛 ValueError，交给任务重试
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.topic_tagging_service import parse_tagging_response

VALID_CODES = {"I.A", "I.B", "II.A", "II.B", "III.C"}


def test_parses_single_and_multiple_codes():
    raw = '{"results": [{"no": 1, "codes": ["II.A"]}, {"no": 2, "codes": ["I.A", "III.C"]}]}'

    assert parse_tagging_response(raw, 2, VALID_CODES) == {1: ["II.A"], 2: ["I.A", "III.C"]}


def test_empty_codes_mean_unresolved():
    raw = '{"results": [{"no": 1, "codes": []}]}'

    assert parse_tagging_response(raw, 1, VALID_CODES) == {1: []}


def test_unknown_codes_are_dropped_and_logged(caplog):
    raw = '{"results": [{"no": 1, "codes": ["II.A", "IX.Z", "VII.B"]}]}'

    with caplog.at_level("WARNING"):
        assert parse_tagging_response(raw, 1, VALID_CODES) == {1: ["II.A"]}

    assert "IX.Z" in caplog.text and "VII.B" in caplog.text


def test_all_unknown_codes_degrade_to_unresolved():
    raw = '{"results": [{"no": 1, "codes": ["IX.Z"]}]}'

    assert parse_tagging_response(raw, 1, VALID_CODES) == {1: []}


def test_codes_are_normalized_and_deduplicated():
    raw = '{"results": [{"no": 1, "codes": [" ii.a ", "II.A"]}]}'

    assert parse_tagging_response(raw, 1, VALID_CODES) == {1: ["II.A"]}


def test_strips_markdown_code_fence():
    raw = '```json\n{"results": [{"no": 1, "codes": ["I.B"]}]}\n```'

    assert parse_tagging_response(raw, 1, VALID_CODES) == {1: ["I.B"]}


def test_accepts_bare_results_array():
    raw = '[{"no": 1, "codes": ["I.A"]}]'

    assert parse_tagging_response(raw, 1, VALID_CODES) == {1: ["I.A"]}


def test_out_of_range_question_numbers_are_ignored():
    raw = '{"results": [{"no": 0, "codes": ["I.A"]}, {"no": 5, "codes": ["I.A"]}, {"no": 2, "codes": ["I.B"]}]}'

    assert parse_tagging_response(raw, 2, VALID_CODES) == {2: ["I.B"]}


def test_missing_question_numbers_are_absent_from_result():
    raw = '{"results": [{"no": 1, "codes": ["I.A"]}]}'

    parsed = parse_tagging_response(raw, 3, VALID_CODES)

    assert parsed == {1: ["I.A"]}
    assert 2 not in parsed and 3 not in parsed


def test_non_list_codes_degrade_to_unresolved():
    raw = '{"results": [{"no": 1, "codes": "II.A"}]}'

    assert parse_tagging_response(raw, 1, VALID_CODES) == {1: []}


def test_invalid_json_raises():
    with pytest.raises(ValueError, match="不是合法 JSON"):
        parse_tagging_response("这不是 JSON", 1, VALID_CODES)


def test_missing_results_array_raises():
    with pytest.raises(ValueError, match="缺少 results 数组"):
        parse_tagging_response('{"foo": "bar"}', 1, VALID_CODES)
