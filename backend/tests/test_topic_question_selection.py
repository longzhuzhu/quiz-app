"""专项练习选题与考点概览的集成测试（in-memory SQLite）

覆盖：
- 域的题目集合是其下所有能力项关联题目的去重并集（跨能力项的题只出现一次）
- 未分类分支只包含没有任何考点关联的题目
- 题库概览的题数勾稽：有考点的题数 + 未分类题数 == 题库总题数
- 人工设定考点整份替换，且拒绝直接关联域级考点
- 人工设过考点的题目不再被批量打标当作待打标题目
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# JSONB → JSON 兼容（必须在 import models 前完成）
from sqlalchemy.dialects.postgresql import JSONB  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(element, compiler, **kw):
    """SQLAlchemy 在 SQLite 方言下把 JSONB 编译为 JSON（仅测试态）。"""
    return "JSON"


from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.core.database import Base  # noqa: E402
from app.models import (  # noqa: E402,F401  —— 导入以注册全部映射
    Exam,
    ExamTopic,
    Question,
    QuestionBank,
    QuestionTopic,
    QuizSession,
    User,
)
from app.models.exam_topic import TOPIC_LEVEL_COMPETENCY, TOPIC_LEVEL_DOMAIN  # noqa: E402
from app.models.question_topic import TOPIC_SOURCE_AI, TOPIC_SOURCE_MANUAL  # noqa: E402
from app.services.topic_service import (  # noqa: E402
    list_bank_topic_overview,
    list_question_ids_for_competency,
    list_question_ids_for_domain,
    list_unclassified_question_ids,
    set_question_topics_manually,
)
from app.services.topic_tagging_service import (  # noqa: E402
    list_untagged_question_ids,
    load_competencies,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def fixture_data(db):
    """两个域、三个能力项、六道题的最小题库。

    q1 只挂 II.A；q2 同时挂 II.A 和 II.B（同域跨能力项）；q3 挂 III.C；
    q4 同时挂 II.A 和 III.C（跨域）；q5、q6 没有任何考点。
    """
    user = User(username="tester", email="t@example.com", password_hash="x")
    db.add(user)
    db.flush()

    exam = Exam(owner_id=user.id, slug="cipt", name="CIPT", short_name="CIPT")
    db.add(exam)
    db.flush()

    bank = QuestionBank(name="题库", exam_id=exam.id)
    other_bank = QuestionBank(name="另一个题库", exam_id=exam.id)
    db.add_all([bank, other_bank])
    db.flush()

    domain_ii = ExamTopic(
        exam_id=exam.id, level=TOPIC_LEVEL_DOMAIN, code="II", name_en="D2", name_zh="域二",
        short_name_zh="域二", blueprint_min=19, blueprint_max=23, order_index=1,
        source_version="4.0.0",
    )
    domain_iii = ExamTopic(
        exam_id=exam.id, level=TOPIC_LEVEL_DOMAIN, code="III", name_en="D3", name_zh="域三",
        short_name_zh="域三", blueprint_min=17, blueprint_max=21, order_index=2,
        source_version="4.0.0",
    )
    db.add_all([domain_ii, domain_iii])
    db.flush()

    comp_iia = ExamTopic(
        exam_id=exam.id, parent_id=domain_ii.id, level=TOPIC_LEVEL_COMPETENCY, code="II.A",
        name_en="C2A", name_zh="能力二A", short_name_zh="二A", blueprint_min=8, blueprint_max=10,
        order_index=1, source_version="4.0.0",
    )
    comp_iib = ExamTopic(
        exam_id=exam.id, parent_id=domain_ii.id, level=TOPIC_LEVEL_COMPETENCY, code="II.B",
        name_en="C2B", name_zh="能力二B", short_name_zh="二B", blueprint_min=6, blueprint_max=8,
        order_index=2, source_version="4.0.0",
    )
    comp_iiic = ExamTopic(
        exam_id=exam.id, parent_id=domain_iii.id, level=TOPIC_LEVEL_COMPETENCY, code="III.C",
        name_en="C3C", name_zh="能力三C", short_name_zh="三C", blueprint_min=4, blueprint_max=6,
        order_index=1, source_version="4.0.0",
    )
    db.add_all([comp_iia, comp_iib, comp_iiic])
    db.flush()

    questions = [
        Question(
            bank_id=bank.id, question_type="single", content=f"Q{i}",
            options=[{"key": "A", "text": "a"}], correct_answer="A", order_index=i,
        )
        for i in range(1, 7)
    ]
    db.add_all(questions)
    db.flush()
    q1, q2, q3, q4, q5, q6 = questions

    db.add_all([
        QuestionTopic(question_id=q1.id, topic_id=comp_iia.id, source=TOPIC_SOURCE_AI),
        QuestionTopic(question_id=q2.id, topic_id=comp_iia.id, source=TOPIC_SOURCE_AI),
        QuestionTopic(question_id=q2.id, topic_id=comp_iib.id, source=TOPIC_SOURCE_AI),
        QuestionTopic(question_id=q3.id, topic_id=comp_iiic.id, source=TOPIC_SOURCE_AI),
        QuestionTopic(question_id=q4.id, topic_id=comp_iia.id, source=TOPIC_SOURCE_AI),
        QuestionTopic(question_id=q4.id, topic_id=comp_iiic.id, source=TOPIC_SOURCE_AI),
    ])
    db.commit()

    return {
        "exam": exam, "bank": bank, "other_bank": other_bank,
        "domain_ii": domain_ii, "domain_iii": domain_iii,
        "comp_iia": comp_iia, "comp_iib": comp_iib, "comp_iiic": comp_iiic,
        "questions": {"q1": q1, "q2": q2, "q3": q3, "q4": q4, "q5": q5, "q6": q6},
    }


def test_domain_selection_unions_competencies_without_duplicates(db, fixture_data):
    q = fixture_data["questions"]

    ids = list_question_ids_for_domain(db, fixture_data["bank"].id, fixture_data["domain_ii"].id)

    # q2 同时挂了 II.A 和 II.B，只能出现一次
    assert ids == sorted([q["q1"].id, q["q2"].id, q["q4"].id])


def test_domain_selection_is_scoped_to_the_bank(db, fixture_data):
    ids = list_question_ids_for_domain(
        db, fixture_data["other_bank"].id, fixture_data["domain_ii"].id
    )

    assert ids == []


def test_domain_without_tagged_questions_returns_empty(db, fixture_data):
    empty_domain = ExamTopic(
        exam_id=fixture_data["exam"].id, level=TOPIC_LEVEL_DOMAIN, code="IV",
        name_en="D4", name_zh="域四", short_name_zh="域四", blueprint_min=7,
        blueprint_max=9, order_index=3, source_version="4.0.0",
    )
    db.add(empty_domain)
    db.commit()

    assert list_question_ids_for_domain(db, fixture_data["bank"].id, empty_domain.id) == []


def test_competency_selection_returns_only_that_competency(db, fixture_data):
    q = fixture_data["questions"]

    ids = list_question_ids_for_competency(
        db, fixture_data["bank"].id, fixture_data["comp_iia"].id
    )

    # q1 只挂 II.A；q2 同时挂 II.A 和 II.B；q4 跨域也挂了 II.A
    assert ids == sorted([q["q1"].id, q["q2"].id, q["q4"].id])


def test_competency_selection_does_not_include_sibling_competency(db, fixture_data):
    q = fixture_data["questions"]

    ids = list_question_ids_for_competency(
        db, fixture_data["bank"].id, fixture_data["comp_iib"].id
    )

    assert ids == [q["q2"].id]
    assert q["q1"].id not in ids
    q = fixture_data["questions"]

    ids = list_unclassified_question_ids(db, fixture_data["bank"].id)

    assert ids == sorted([q["q5"].id, q["q6"].id])


def test_overview_counts_reconcile_with_bank_total(db, fixture_data):
    overview = list_bank_topic_overview(db, fixture_data["exam"].id, fixture_data["bank"].id)

    counts = {item["code"]: item["question_count"] for item in overview["topics"]}
    assert counts == {"II": 3, "III": 2}
    assert overview["unclassified_count"] == 2
    assert overview["total_questions"] == 6

    # 跨域的 q4 在两个域各计一次，所以域计数之和不等于总数；
    # 勾稽的是「有考点的题数 + 未分类题数 == 总数」
    classified = overview["total_questions"] - overview["unclassified_count"]
    assert classified == 4


def test_overview_nests_competency_counts_under_domains(db, fixture_data):
    overview = list_bank_topic_overview(db, fixture_data["exam"].id, fixture_data["bank"].id)
    by_code = {item["code"]: item for item in overview["topics"]}

    ii_counts = {c["code"]: c["question_count"] for c in by_code["II"]["competencies"]}
    iii_counts = {c["code"]: c["question_count"] for c in by_code["III"]["competencies"]}

    # q1,q2,q4 挂 II.A；q2 挂 II.B；q3,q4 挂 III.C
    assert ii_counts == {"II.A": 3, "II.B": 1}
    assert iii_counts == {"III.C": 2}
    assert [c["code"] for c in by_code["II"]["competencies"]] == ["II.A", "II.B"]
    # 界面编号按 order_index 生成：fixture 里 II 是第 1 个域
    assert by_code["II"]["number"] == "1"
    assert [c["number"] for c in by_code["II"]["competencies"]] == ["1.1", "1.2"]
    assert by_code["III"]["number"] == "2"
    assert [c["number"] for c in by_code["III"]["competencies"]] == ["2.1"]


def test_tagging_prompt_lists_competencies_in_outline_order(db, fixture_data):
    """打标 prompt 的考纲部分必须按域序展开：order_index 每域都从 1 开始，
    只按它排会串成 II.A、III.C、II.B。"""
    competencies = load_competencies(db, fixture_data["exam"].id)

    assert [topic.code for topic in competencies] == ["II.A", "II.B", "III.C"]


def test_manual_topics_replace_existing_links(db, fixture_data):
    q2 = fixture_data["questions"]["q2"]

    set_question_topics_manually(db, q2, [fixture_data["comp_iiic"].id])
    db.commit()

    links = db.query(QuestionTopic).filter_by(question_id=q2.id).all()
    assert [(link.topic_id, link.source) for link in links] == [
        (fixture_data["comp_iiic"].id, TOPIC_SOURCE_MANUAL)
    ]


def test_manual_topics_keep_ai_source_when_set_is_unchanged(db, fixture_data):
    """题目管理页每次保存都会带上 topic_ids，考点没变时不应把 AI 关联改成人工"""
    q1 = fixture_data["questions"]["q1"]

    set_question_topics_manually(db, q1, [fixture_data["comp_iia"].id])
    db.commit()

    links = db.query(QuestionTopic).filter_by(question_id=q1.id).all()
    assert [(link.topic_id, link.source) for link in links] == [
        (fixture_data["comp_iia"].id, TOPIC_SOURCE_AI)
    ]


def test_manual_topics_reject_domain_level_topics(db, fixture_data):
    q5 = fixture_data["questions"]["q5"]

    with pytest.raises(ValueError, match="不可直接关联"):
        set_question_topics_manually(db, q5, [fixture_data["domain_ii"].id])


def test_manual_topics_reject_topics_from_another_exam(db, fixture_data):
    other_user = User(username="other", email="o@example.com", password_hash="x")
    db.add(other_user)
    db.flush()
    other_exam = Exam(owner_id=other_user.id, slug="cipm", name="CIPM", short_name="CIPM")
    db.add(other_exam)
    db.flush()
    foreign_topic = ExamTopic(
        exam_id=other_exam.id, level=TOPIC_LEVEL_COMPETENCY, code="X.A", name_en="X",
        name_zh="外域", short_name_zh="外域", blueprint_min=1, blueprint_max=2,
        order_index=1, source_version="4.0.0",
    )
    db.add(foreign_topic)
    db.commit()

    with pytest.raises(ValueError, match="不可直接关联"):
        set_question_topics_manually(db, fixture_data["questions"]["q5"], [foreign_topic.id])


def test_manually_tagged_questions_are_not_retagged(db, fixture_data):
    q = fixture_data["questions"]

    # 打标前，只有两道无关联的题待打标
    assert list_untagged_question_ids(db, fixture_data["bank"].id) == sorted(
        [q["q5"].id, q["q6"].id]
    )

    set_question_topics_manually(db, q["q5"], [fixture_data["comp_iib"].id])
    db.commit()

    # 人工设过考点后，这道题不再被当作待打标，AI 不会在人工结果上叠加标签
    assert list_untagged_question_ids(db, fixture_data["bank"].id) == [q["q6"].id]


def _competency_flags(overview, code):
    for domain in overview["topics"]:
        for competency in domain["competencies"]:
            if competency["code"] == code:
                return competency["practiced"], competency["in_progress"]
    raise AssertionError(f"missing competency {code}")


def _add_topic_session(db, user_id, bank_id, topic_id, *, completed, mode="topic"):
    db.add(
        QuizSession(
            user_id=user_id,
            bank_id=bank_id,
            mode=mode,
            topic_id=topic_id,
            total_questions=1,
            is_completed=completed,
        )
    )


def test_overview_practice_flags_default_false_without_user(db, fixture_data):
    overview = list_bank_topic_overview(db, fixture_data["exam"].id, fixture_data["bank"].id)

    assert _competency_flags(overview, "II.A") == (False, False)
    assert overview["unclassified_practiced"] is False
    assert overview["unclassified_in_progress"] is False


def test_overview_marks_practiced_and_in_progress_for_current_user_bank(db, fixture_data):
    user_id = fixture_data["exam"].owner_id
    bank_id = fixture_data["bank"].id
    _add_topic_session(db, user_id, bank_id, fixture_data["comp_iia"].id, completed=True)
    _add_topic_session(db, user_id, bank_id, fixture_data["comp_iib"].id, completed=False)
    _add_topic_session(db, user_id, bank_id, None, completed=True)
    _add_topic_session(db, user_id, bank_id, None, completed=False)
    db.commit()

    overview = list_bank_topic_overview(
        db, fixture_data["exam"].id, bank_id, user_id=user_id
    )

    assert _competency_flags(overview, "II.A") == (True, False)
    assert _competency_flags(overview, "II.B") == (False, True)
    assert _competency_flags(overview, "III.C") == (False, False)
    assert overview["unclassified_practiced"] is True
    assert overview["unclassified_in_progress"] is True


def test_overview_practice_flags_ignore_other_mode_bank_and_user(db, fixture_data):
    owner_id = fixture_data["exam"].owner_id
    other = User(username="other2", email="o2@example.com", password_hash="x")
    db.add(other)
    db.flush()
    _add_topic_session(
        db, owner_id, fixture_data["bank"].id, fixture_data["comp_iia"].id,
        completed=True, mode="sequential",
    )
    _add_topic_session(
        db, owner_id, fixture_data["other_bank"].id, fixture_data["comp_iia"].id,
        completed=True,
    )
    _add_topic_session(
        db, other.id, fixture_data["bank"].id, fixture_data["comp_iib"].id,
        completed=True,
    )
    _add_topic_session(
        db, owner_id, fixture_data["bank"].id, fixture_data["domain_ii"].id,
        completed=True,
    )
    db.commit()

    overview = list_bank_topic_overview(
        db, fixture_data["exam"].id, fixture_data["bank"].id, user_id=owner_id
    )

    assert _competency_flags(overview, "II.A") == (False, False)
    assert _competency_flags(overview, "II.B") == (False, False)


def test_overview_practiced_and_in_progress_can_coexist(db, fixture_data):
    user_id = fixture_data["exam"].owner_id
    bank_id = fixture_data["bank"].id
    _add_topic_session(db, user_id, bank_id, fixture_data["comp_iia"].id, completed=True)
    _add_topic_session(db, user_id, bank_id, fixture_data["comp_iia"].id, completed=False)
    db.commit()

    overview = list_bank_topic_overview(
        db, fixture_data["exam"].id, bank_id, user_id=user_id
    )

    assert _competency_flags(overview, "II.A") == (True, True)


def test_clearing_manual_topics_returns_question_to_untagged(db, fixture_data):
    q1 = fixture_data["questions"]["q1"]

    set_question_topics_manually(db, q1, [])
    db.commit()

    assert q1.id in list_untagged_question_ids(db, fixture_data["bank"].id)
    assert q1.id in list_unclassified_question_ids(db, fixture_data["bank"].id)
