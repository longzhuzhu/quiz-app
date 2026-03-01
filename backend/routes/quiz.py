import json
from datetime import datetime, timezone

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy import func

from models import db, Question, QuizSession, QuizAnswer, WrongAnswer

quiz_bp = Blueprint('quiz', __name__)


@quiz_bp.route('/start', methods=['POST'])
@jwt_required()
def start_quiz():
    user_id = int(get_jwt_identity())
    data = request.get_json()
    bank_id = data['bank_id']
    mode = data.get('mode', 'sequential')
    question_count = data.get('question_count')

    query = Question.query.filter_by(bank_id=bank_id)
    if mode == 'random':
        query = query.order_by(func.random())
    else:
        query = query.order_by(Question.order_index)

    if question_count:
        query = query.limit(question_count)

    questions = query.all()
    if not questions:
        return jsonify({'error': '该题库没有题目'}), 400

    session = QuizSession(
        user_id=user_id,
        bank_id=bank_id,
        mode=mode,
        total_questions=len(questions),
        question_ids=json.dumps([q.id for q in questions]),
    )
    db.session.add(session)
    db.session.commit()

    questions_out = []
    for q in questions:
        questions_out.append({
            'id': q.id,
            'question_type': q.question_type,
            'content': q.content,
            'content_zh': q.content_zh,
            'options': json.loads(q.options),
            'explanation': q.explanation,
            'explanation_zh': q.explanation_zh,
        })

    return jsonify({
        'session': {
            'id': session.id,
            'bank_id': session.bank_id,
            'mode': session.mode,
            'total_questions': session.total_questions,
        },
        'questions': questions_out,
    })


@quiz_bp.route('/answer', methods=['POST'])
@jwt_required()
def submit_answer():
    user_id = int(get_jwt_identity())
    data = request.get_json()
    session_id = data['session_id']
    question_id = data['question_id']
    user_answer = data['user_answer']

    session = QuizSession.query.get_or_404(session_id)
    if session.user_id != user_id:
        return jsonify({'error': '无权限'}), 403
    if session.is_completed:
        return jsonify({'error': '答题已结束'}), 400

    existing = QuizAnswer.query.filter_by(
        session_id=session_id, question_id=question_id
    ).first()
    if existing:
        return jsonify({'error': '该题已作答'}), 400

    question = Question.query.get_or_404(question_id)
    is_correct = user_answer.strip().upper() == question.correct_answer.strip().upper()

    answer = QuizAnswer(
        session_id=session_id,
        question_id=question_id,
        user_answer=user_answer,
        is_correct=is_correct,
    )
    db.session.add(answer)

    session.answered_count += 1
    if is_correct:
        session.correct_count += 1
    else:
        # Auto-collect wrong answer
        wrong = WrongAnswer.query.filter_by(
            user_id=user_id, question_id=question_id
        ).first()
        if wrong:
            wrong.wrong_count += 1
            wrong.last_wrong_at = datetime.now(timezone.utc)
            wrong.is_resolved = False
        else:
            wrong = WrongAnswer(user_id=user_id, question_id=question_id)
            db.session.add(wrong)

    db.session.commit()

    return jsonify({
        'is_correct': is_correct,
        'correct_answer': question.correct_answer,
        'explanation': question.explanation,
        'explanation_zh': question.explanation_zh,
    })


@quiz_bp.route('/finish', methods=['POST'])
@jwt_required()
def finish_quiz():
    user_id = int(get_jwt_identity())
    data = request.get_json()
    session = QuizSession.query.get_or_404(data['session_id'])
    if session.user_id != user_id:
        return jsonify({'error': '无权限'}), 403

    session.is_completed = True
    session.completed_at = datetime.now(timezone.utc)
    db.session.commit()

    return jsonify({
        'session': {
            'id': session.id,
            'total_questions': session.total_questions,
            'answered_count': session.answered_count,
            'correct_count': session.correct_count,
            'is_completed': True,
            'accuracy': round(session.correct_count / max(session.answered_count, 1) * 100, 1),
        }
    })


@quiz_bp.route('/history', methods=['GET'])
@jwt_required()
def history():
    user_id = int(get_jwt_identity())
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)

    pagination = QuizSession.query.filter_by(user_id=user_id)\
        .order_by(QuizSession.created_at.desc())\
        .paginate(page=page, per_page=per_page, error_out=False)

    result = []
    for s in pagination.items:
        result.append({
            'id': s.id,
            'bank_id': s.bank_id,
            'bank_name': s.bank.name if s.bank else '',
            'mode': s.mode,
            'total_questions': s.total_questions,
            'answered_count': s.answered_count,
            'correct_count': s.correct_count,
            'is_completed': s.is_completed,
            'accuracy': round(s.correct_count / max(s.answered_count, 1) * 100, 1),
            'created_at': s.created_at.isoformat(),
            'completed_at': s.completed_at.isoformat() if s.completed_at else None,
        })
    return jsonify({
        'items': result,
        'total': pagination.total,
        'page': pagination.page,
        'pages': pagination.pages,
    })


@quiz_bp.route('/history', methods=['DELETE'])
@jwt_required()
def clear_history():
    user_id = int(get_jwt_identity())
    sessions = QuizSession.query.filter_by(user_id=user_id).all()
    for s in sessions:
        db.session.delete(s)
    db.session.commit()
    return jsonify({'message': '已清空答题历史'})


@quiz_bp.route('/session/<int:session_id>', methods=['GET'])
@jwt_required()
def session_detail(session_id):
    user_id = int(get_jwt_identity())
    session = QuizSession.query.get_or_404(session_id)
    if session.user_id != user_id:
        return jsonify({'error': '无权限'}), 403

    answers = QuizAnswer.query.filter_by(session_id=session_id).all()
    answers_out = []
    for a in answers:
        q = a.question
        answers_out.append({
            'question_id': a.question_id,
            'question_content': q.content,
            'question_content_zh': q.content_zh,
            'question_type': q.question_type,
            'options': json.loads(q.options),
            'user_answer': a.user_answer,
            'correct_answer': q.correct_answer,
            'is_correct': a.is_correct,
            'explanation': q.explanation,
            'explanation_zh': q.explanation_zh,
        })

    # 未完成的会话返回完整题目列表，用于页面刷新后恢复答题
    questions_out = []
    if not session.is_completed and session.question_ids:
        q_ids = json.loads(session.question_ids)
        answered_ids = {a.question_id for a in answers}
        all_questions = Question.query.filter(Question.id.in_(q_ids)).all()
        q_map = {q.id: q for q in all_questions}
        for qid in q_ids:
            q = q_map.get(qid)
            if q:
                questions_out.append({
                    'id': q.id,
                    'question_type': q.question_type,
                    'content': q.content,
                    'content_zh': q.content_zh,
                    'options': json.loads(q.options),
                    'explanation': q.explanation,
                    'explanation_zh': q.explanation_zh,
                    'answered': qid in answered_ids,
                })

    result = {
        'session': {
            'id': session.id,
            'bank_id': session.bank_id,
            'bank_name': session.bank.name if session.bank else '',
            'mode': session.mode,
            'total_questions': session.total_questions,
            'answered_count': session.answered_count,
            'correct_count': session.correct_count,
            'is_completed': session.is_completed,
            'accuracy': round(session.correct_count / max(session.answered_count, 1) * 100, 1),
            'created_at': session.created_at.isoformat(),
            'completed_at': session.completed_at.isoformat() if session.completed_at else None,
        },
        'answers': answers_out,
    }
    if questions_out:
        result['questions'] = questions_out
    return jsonify(result)
