"""本场答题统计口径。

设总题数 T、已答数 A、正确数 C：错误数 E = A - C，未答数 U = T - A，三者与 T 守恒。
普通练习本场正确率以已答数为分母，模拟考试以本场总题数为分母；分母为 0 时返回 0.0，
不产生 NaN 或除零异常。与首页「滚动正确率」口径无关。
"""

from __future__ import annotations


def session_stats(*, total: int, answered: int, correct: int, mode: str) -> dict:
    """返回本场错误数、未答数、正确率分母口径与正确率。"""
    wrong = max(answered - correct, 0)
    unanswered = max(total - answered, 0)
    basis = "total" if mode == "exam" else "answered"
    denominator = total if basis == "total" else answered
    accuracy = round(correct / denominator * 100, 1) if denominator else 0.0
    return {
        "wrong_count": wrong,
        "unanswered_count": unanswered,
        "accuracy_basis": basis,
        "accuracy": accuracy,
    }
