from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from models import Question, User
from services.ai_service import translate_question, explain_question

ai_bp = Blueprint('ai', __name__)


@ai_bp.route('/translate', methods=['POST'])
@jwt_required()
def translate():
    data = request.get_json()
    question = Question.query.get_or_404(data['question_id'])

    if question.content_zh:
        return jsonify({
            'content_zh': question.content_zh,
            'cached': True,
        })

    try:
        result = translate_question(question)
        return jsonify({**result, 'cached': False})
    except Exception as e:
        return jsonify({'error': f'翻译失败: {str(e)}'}), 500


@ai_bp.route('/translate/batch', methods=['POST'])
@jwt_required()
def translate_batch():
    user = User.query.get(int(get_jwt_identity()))
    if not user.is_admin:
        return jsonify({'error': '需要管理员权限'}), 403

    data = request.get_json()
    bank_id = data.get('bank_id')
    questions = Question.query.filter_by(bank_id=bank_id)\
        .filter(Question.content_zh.is_(None)).all()

    success = 0
    errors = 0
    for q in questions:
        try:
            translate_question(q)
            success += 1
        except Exception:
            errors += 1

    return jsonify({'success': success, 'errors': errors, 'total': len(questions)})


@ai_bp.route('/explain', methods=['POST'])
@jwt_required()
def explain():
    data = request.get_json()
    question = Question.query.get_or_404(data['question_id'])

    if question.explanation:
        return jsonify({
            'explanation': question.explanation,
            'explanation_zh': question.explanation_zh,
            'cached': True,
        })

    try:
        result = explain_question(question)
        return jsonify({**result, 'cached': False})
    except Exception as e:
        return jsonify({'error': f'解析失败: {str(e)}'}), 500
