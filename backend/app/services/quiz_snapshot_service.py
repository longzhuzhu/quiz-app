"""答题会话本场题目快照与完成冻结。

快照只保存判分依据（题干、选项、题型、当场正确答案），不含翻译与 AI 解析；
与 ``question_ids`` 同序，通过数组下标表达题号。JSONB 字段必须整字段重新赋值，
不做就地 mutate，否则 flush 不会发出 UPDATE。
"""

from __future__ import annotations

import json

from app.models.question import Question
from app.models.quiz import QuizAnswer, QuizSession


def load_options(question: Question) -> list | dict:
    """加载题目选项，兼容 JSONB 和 JSON 字符串格式。"""
    options = question.options
    if isinstance(options, str):
        return json.loads(options)
    return options


def snapshot_entry(question: Question) -> dict:
    """构造单题的快照条目，字段固定为五个判分依据。"""
    return {
        "question_id": question.id,
        "question_type": question.question_type,
        "content": question.content,
        "options": load_options(question),
        "correct_answer": question.correct_answer,
    }


def snapshot_entries(questions: list[Question]) -> list[dict]:
    """按题目顺序构造本场快照；只含判分依据，不含 AI 辅助内容。"""
    return [snapshot_entry(question) for question in questions]


def sync_snapshot_correct_answer(session: QuizSession, question_id: int, correct_answer: str) -> None:
    """更新进行中会话快照里该题的当场正确答案；不动其他会话，也不新增条目。

    快照为 NULL（旧会话）或该题不在本场时不做任何事。
    """
    if not session.question_snapshot:
        return
    updated = []
    changed = False
    for entry in session.question_snapshot:
        if isinstance(entry, dict) and entry.get("question_id") == question_id:
            updated.append({**entry, "correct_answer": correct_answer})
            changed = True
        else:
            updated.append(entry)
    if changed:
        session.question_snapshot = updated


def freeze_final_answers(question_ids: list[int], answers: list[QuizAnswer]) -> dict:
    """按本场题目顺序冻结各题最终作答与判定；未答题显式写 None。"""
    by_question_id = {answer.question_id: answer for answer in answers}
    frozen = {}
    for question_id in question_ids:
        answer = by_question_id.get(question_id)
        if answer is None:
            frozen[str(question_id)] = None
        else:
            frozen[str(question_id)] = {
                "user_answer": answer.user_answer,
                "is_correct": bool(answer.is_correct),
            }
    return frozen
