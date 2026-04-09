import json

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy import func

from models import db, WrongAnswer, Question, QuizSession, UserQuestionStat

wrong_bp = Blueprint('wrong', __name__)


def _get_user_question_counts(user_id, question_ids):
    if not question_ids:
        return {}

    stats = UserQuestionStat.query.filter(
        UserQuestionStat.user_id == user_id,
        UserQuestionStat.question_id.in_(question_ids),
    ).all()
    return {item.question_id: item.answer_count for item in stats}


@wrong_bp.route('/', methods=['GET'])
@jwt_required()
def list_wrong():
    user_id = int(get_jwt_identity())
    bank_id = request.args.get('bank_id', type=int)

    query = WrongAnswer.query.filter_by(user_id=user_id, is_resolved=False)
    if bank_id:
        query = query.join(Question).filter(Question.bank_id == bank_id)

    wrongs = query.order_by(WrongAnswer.last_wrong_at.desc()).all()
    result = []
    for w in wrongs:
        q = w.question
        result.append({
            'id': w.id,
            'question_id': w.question_id,
            'wrong_count': w.wrong_count,
            'last_wrong_at': w.last_wrong_at.isoformat(),
            'question': {
                'id': q.id,
                'bank_id': q.bank_id,
                'question_type': q.question_type,
                'content': q.content,
                'content_zh': q.content_zh,
                'options': json.loads(q.options),
                'correct_answer': q.correct_answer,
                'explanation': q.explanation,
                'explanation_zh': q.explanation_zh,
            }
        })
    return jsonify(result)


@wrong_bp.route('/practice', methods=['POST'])
@jwt_required()
def practice_wrong():
    user_id = int(get_jwt_identity())
    data = request.get_json()
    bank_id = data.get('bank_id')

    query = WrongAnswer.query.filter_by(user_id=user_id, is_resolved=False)
    if bank_id:
        query = query.join(Question).filter(Question.bank_id == bank_id)

    wrongs = query.all()
    if not wrongs:
        return jsonify({'error': '没有错题'}), 400

    question_ids = [w.question_id for w in wrongs]
    questions = Question.query.filter(Question.id.in_(question_ids)).all()
    question_map = {q.id: q for q in questions}
    ordered_questions = [question_map[qid] for qid in question_ids if qid in question_map]
    counts = _get_user_question_counts(user_id, question_ids)

    # Use the first question's bank_id for the session
    first_bank_id = bank_id or ordered_questions[0].bank_id
    session = QuizSession(
        user_id=user_id,
        bank_id=first_bank_id,
        mode='wrong_practice',
        total_questions=len(ordered_questions),
        question_ids=json.dumps(question_ids),
    )
    db.session.add(session)
    db.session.commit()

    questions_out = []
    for q in ordered_questions:
        questions_out.append({
            'id': q.id,
            'question_type': q.question_type,
            'content': q.content,
            'content_zh': q.content_zh,
            'options': json.loads(q.options),
            'explanation': q.explanation,
            'explanation_zh': q.explanation_zh,
            'user_answer_count': counts.get(q.id, 0),
        })

    return jsonify({
        'session': {
            'id': session.id,
            'bank_id': first_bank_id,
            'mode': 'wrong_practice',
            'total_questions': len(questions),
        },
        'questions': questions_out,
    })


@wrong_bp.route('/<int:wrong_id>/resolve', methods=['PUT'])
@jwt_required()
def resolve_wrong(wrong_id):
    user_id = int(get_jwt_identity())
    wrong = WrongAnswer.query.get_or_404(wrong_id)
    if wrong.user_id != user_id:
        return jsonify({'error': '无权限'}), 403
    wrong.is_resolved = True
    db.session.commit()
    return jsonify({'message': '已标记为掌握'})


@wrong_bp.route('/stats', methods=['GET'])
@jwt_required()
def wrong_stats():
    user_id = int(get_jwt_identity())
    total = WrongAnswer.query.filter_by(user_id=user_id, is_resolved=False).count()
    resolved = WrongAnswer.query.filter_by(user_id=user_id, is_resolved=True).count()
    return jsonify({'unresolved': total, 'resolved': resolved, 'total': total + resolved})
