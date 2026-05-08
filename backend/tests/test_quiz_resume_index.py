import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.routes.quiz import _compute_resume_index


def _answer(question_id, answered_at, answer_id):
    return SimpleNamespace(question_id=question_id, answered_at=answered_at, id=answer_id)


def test_resume_index_moves_to_question_after_latest_answer():
    base_time = datetime(2026, 5, 7, tzinfo=timezone.utc)
    answers = [
        _answer(101, base_time, 1),
        _answer(102, base_time + timedelta(minutes=1), 2),
    ]

    assert _compute_resume_index([101, 102, 103], answers) == 2


def test_resume_index_uses_answer_id_as_tie_breaker():
    answered_at = datetime(2026, 5, 7, tzinfo=timezone.utc)
    answers = [
        _answer(101, answered_at, 1),
        _answer(102, answered_at, 2),
    ]

    assert _compute_resume_index([101, 102, 103], answers) == 2


def test_resume_index_clamps_when_latest_answer_is_last_question():
    answered_at = datetime(2026, 5, 7, tzinfo=timezone.utc)
    answers = [_answer(103, answered_at, 1)]

    assert _compute_resume_index([101, 102, 103], answers) == 2


def test_resume_index_starts_at_first_question_without_answers():
    assert _compute_resume_index([101, 102, 103], []) == 0


def test_resume_index_ignores_answers_outside_session_question_order():
    base_time = datetime(2026, 5, 7, tzinfo=timezone.utc)
    answers = [
        _answer(101, base_time, 1),
        _answer(999, base_time + timedelta(minutes=1), 2),
    ]

    assert _compute_resume_index([101, 102, 103], answers) == 1
