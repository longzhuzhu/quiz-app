import json

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from models import db, Question, QuestionBank, User

questions_bp = Blueprint('questions', __name__)


def question_to_dict(q, include_answer=True):
    d = {
        'id': q.id,
        'bank_id': q.bank_id,
        'question_type': q.question_type,
        'content': q.content,
        'content_zh': q.content_zh,
        'options': json.loads(q.options),
        'order_index': q.order_index,
        'explanation': q.explanation,
        'explanation_zh': q.explanation_zh,
        'created_at': q.created_at.isoformat(),
    }
    if include_answer:
        d['correct_answer'] = q.correct_answer
    return d


@questions_bp.route('/banks/<int:bank_id>/questions', methods=['GET'])
@jwt_required()
def list_questions(bank_id):
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    pagination = Question.query.filter_by(bank_id=bank_id)\
        .order_by(Question.order_index)\
        .paginate(page=page, per_page=per_page, error_out=False)
    return jsonify({
        'questions': [question_to_dict(q) for q in pagination.items],
        'total': pagination.total,
        'page': page,
        'pages': pagination.pages,
    })


@questions_bp.route('/', methods=['POST'])
@jwt_required()
def create_question():
    user = User.query.get(int(get_jwt_identity()))
    if not user.is_admin:
        return jsonify({'error': '需要管理员权限'}), 403
    data = request.get_json()
    q = Question(
        bank_id=data['bank_id'],
        question_type=data['question_type'],
        content=data['content'],
        options=json.dumps(data['options']),
        correct_answer=data['correct_answer'],
    )
    db.session.add(q)
    bank = QuestionBank.query.get(data['bank_id'])
    bank.question_count = Question.query.filter_by(bank_id=bank.id).count() + 1
    db.session.commit()
    return jsonify(question_to_dict(q)), 201


@questions_bp.route('/<int:question_id>', methods=['PUT'])
@jwt_required()
def update_question(question_id):
    user = User.query.get(int(get_jwt_identity()))
    if not user.is_admin:
        return jsonify({'error': '需要管理员权限'}), 403
    q = Question.query.get_or_404(question_id)
    data = request.get_json()
    if 'content' in data:
        q.content = data['content']
    if 'options' in data:
        q.options = json.dumps(data['options'])
    if 'correct_answer' in data:
        q.correct_answer = data['correct_answer']
    if 'question_type' in data:
        q.question_type = data['question_type']
    db.session.commit()
    return jsonify(question_to_dict(q))


@questions_bp.route('/<int:question_id>', methods=['DELETE'])
@jwt_required()
def delete_question(question_id):
    user = User.query.get(int(get_jwt_identity()))
    if not user.is_admin:
        return jsonify({'error': '需要管理员权限'}), 403
    q = Question.query.get_or_404(question_id)
    bank = QuestionBank.query.get(q.bank_id)
    db.session.delete(q)
    bank.question_count = max(0, bank.question_count - 1)
    db.session.commit()
    return jsonify({'message': '题目已删除'})
