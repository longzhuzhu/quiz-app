"""更正答案：规范化比较、校验、本场重判，不碰错题本。"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.answer_keys import (  # noqa: E402
    answers_equivalent,
    format_answer_keys,
    parse_answer_keys,
)
from app.services.question_service import (  # noqa: E402
    apply_session_regrade,
    update_question_correct_answer,
    validate_correct_answer_keys,
)


def _question(**overrides):
    question = MagicMock(name="question")
    question.id = 7
    question.question_type = "single"
    question.options = [
        {"key": "A", "text": "opt a"},
        {"key": "B", "text": "opt b"},
        {"key": "C", "text": "opt c"},
    ]
    question.correct_answer = "B"
    question.explanation = "en"
    question.explanation_zh = "zh"
    for key, value in overrides.items():
        setattr(question, key, value)
    return question


def _exam():
    return SimpleNamespace(id=3, owner_id=9)


def test_parse_answer_keys_strips_and_drops_empty():
    assert parse_answer_keys(" B, C ") == ["B", "C"]
    assert parse_answer_keys("B.") == ["B"]
    assert parse_answer_keys("「B」") == ["B"]
    assert parse_answer_keys("") == []


def test_answers_equivalent_ignores_order_case_and_spaces():
    assert answers_equivalent("B", "b") is True
    assert answers_equivalent("A,C", "C,A") is True
    assert answers_equivalent("A, C", "A,C") is True
    assert answers_equivalent("B", "C") is False


def test_format_answer_keys_matches_bank_style():
    assert format_answer_keys(["C", "A"]) == "A,C"
    assert format_answer_keys(["B"]) == "B"


def test_validate_rejects_empty_and_unknown_keys():
    question = _question()
    with pytest.raises(ValueError, match="不能为空"):
        validate_correct_answer_keys("", question)
    with pytest.raises(ValueError, match="不属于该题"):
        validate_correct_answer_keys("Z", question)


def test_validate_single_requires_exactly_one_key():
    question = _question(question_type="single")
    with pytest.raises(ValueError, match="恰好有一个"):
        validate_correct_answer_keys("A,C", question)
    assert validate_correct_answer_keys("C", question) == "C"


def test_validate_truefalse_requires_exactly_one_key():
    question = _question(question_type="truefalse")
    with pytest.raises(ValueError, match="恰好有一个"):
        validate_correct_answer_keys("A,B", question)


def test_validate_multiple_requires_at_least_one_key():
    question = _question(question_type="multiple")
    assert validate_correct_answer_keys("A,C", question) == "A,C"
    assert validate_correct_answer_keys("B", question) == "B"


def test_apply_session_regrade_wrong_to_right():
    session = SimpleNamespace(correct_count=2)
    answer = SimpleNamespace(user_answer="C", is_correct=False)
    assert apply_session_regrade(session, answer, "C") is True
    assert answer.is_correct is True
    assert session.correct_count == 3


def test_apply_session_regrade_right_to_wrong():
    session = SimpleNamespace(correct_count=2)
    answer = SimpleNamespace(user_answer="B", is_correct=True)
    assert apply_session_regrade(session, answer, "C") is False
    assert answer.is_correct is False
    assert session.correct_count == 1


def test_apply_session_regrade_still_wrong_does_not_change_count():
    session = SimpleNamespace(correct_count=2)
    answer = SimpleNamespace(user_answer="A", is_correct=False)
    apply_session_regrade(session, answer, "C")
    assert answer.is_correct is False
    assert session.correct_count == 2


def test_update_same_answer_is_noop(monkeypatch):
    db = MagicMock(name="db")
    question = _question()
    monkeypatch.setattr(
        "app.services.question_service.record_accuracy_snapshot",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "app.services.question_service.clear_question_explanation",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not clear")),
    )

    result = update_question_correct_answer(
        db, question, _exam(), correct_answer="b", session_id=None
    )

    assert result["correct_answer"] == "B"
    assert result["explanation_zh"] == "zh"
    assert question.explanation_zh == "zh"
    db.commit.assert_not_called()
    db.add.assert_not_called()


def test_update_different_answer_clears_explanation_without_session(monkeypatch):
    db = MagicMock(name="db")
    question = _question()
    cleared = {"called": False}

    def fake_clear(_db, target):
        cleared["called"] = True
        target.explanation = None
        target.explanation_zh = None

    monkeypatch.setattr("app.services.question_service.clear_question_explanation", fake_clear)
    monkeypatch.setattr(
        "app.services.question_service.record_accuracy_snapshot",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("no snapshot without regrade")),
    )

    result = update_question_correct_answer(
        db, question, _exam(), correct_answer="C", session_id=None
    )

    assert question.correct_answer == "C"
    assert cleared["called"] is True
    assert result["explanation_zh"] is None
    assert result["is_correct"] is None
    db.commit.assert_called_once()
    db.add.assert_not_called()


def test_update_regrades_current_session_only(monkeypatch):
    exam = _exam()
    question = _question()
    session = MagicMock(name="session")
    session.id = 12
    session.user_id = 9
    session.bank.exam_id = exam.id
    session.correct_count = 1
    quiz_answer = SimpleNamespace(user_answer="C", is_correct=False, question_id=question.id)

    db = MagicMock(name="db")
    db.get.return_value = session
    db.query.return_value.filter_by.return_value.first.return_value = quiz_answer

    snapshot_calls = []

    def fake_snapshot(*args, **kwargs):
        snapshot_calls.append(kwargs)

    monkeypatch.setattr("app.services.question_service.record_accuracy_snapshot", fake_snapshot)
    monkeypatch.setattr(
        "app.services.question_service.clear_question_explanation",
        lambda _db, target: setattr(target, "explanation_zh", None) or setattr(target, "explanation", None),
    )

    result = update_question_correct_answer(
        db, question, exam, correct_answer="C", session_id=12, local_date="2026-09-10"
    )

    assert question.correct_answer == "C"
    assert quiz_answer.is_correct is True
    assert session.correct_count == 2
    assert result["is_correct"] is True
    assert result["explanation_zh"] is None
    assert snapshot_calls
    assert snapshot_calls[0]["user_id"] == 9
    assert snapshot_calls[0]["exam_id"] == exam.id
    assert snapshot_calls[0]["local_date"] == "2026-09-10"
    db.commit.assert_called_once()
    db.add.assert_not_called()


def test_update_does_not_import_or_touch_wrong_answer():
    import app.services.question_service as question_service

    assert "WrongAnswer" not in question_service.__dict__
    assert "UserQuestionStat" not in question_service.__dict__
