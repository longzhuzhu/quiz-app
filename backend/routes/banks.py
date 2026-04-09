import json

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy.exc import SQLAlchemyError

from models import (
    db,
    QuestionBank,
    Question,
    User,
    BankWordFrequency,
    UserBankWordProgress,
    QuizSession,
    QuizAnswer,
    WrongAnswer,
    BankWordExclusion,
)
from services.import_service import parse_file, build_bank_word_frequencies
from services.ai_service import batch_translate_terms
from services.job_service import JOB_TYPE_BANK_FREQUENT_TRANSLATE, build_scope_key, invalidate_active_scope

banks_bp = Blueprint('banks', __name__)


def _normalize_options(options):
    return json.dumps(options, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def _question_signature(question_type, content, options, correct_answer):
    return (
        question_type,
        (content or '').strip(),
        _normalize_options(options),
        (correct_answer or '').strip().upper(),
    )


def _translate_frequency_batch(batch, start_index):
    try:
        translations = batch_translate_terms([
            {'id': index, 'term': item['term']}
            for index, item in enumerate(batch, start=start_index)
        ])
        return {
            item['id']: item.get('term_zh')
            for item in translations
            if item.get('term_zh')
        }
    except Exception:
        if len(batch) == 1:
            return {}

    middle = len(batch) // 2
    translation_map = _translate_frequency_batch(batch[:middle], start_index)
    translation_map.update(_translate_frequency_batch(batch[middle:], start_index + middle))
    return translation_map



def translate_bank_word_frequencies(items):
    if not items:
        return items

    translation_map = {}
    batch_size = 100

    for start in range(0, len(items), batch_size):
        batch = items[start:start + batch_size]
        translation_map.update(_translate_frequency_batch(batch, start + 1))

    translated_items = []
    for index, item in enumerate(items, start=1):
        translated_items.append({
            **item,
            'term_zh': translation_map.get(index),
        })
    return translated_items


def bank_to_dict(bank):
    return {
        'id': bank.id,
        'name': bank.name,
        'description': bank.description,
        'source_filename': bank.source_filename,
        'question_count': bank.question_count,
        'created_at': bank.created_at.isoformat(),
    }


@banks_bp.route('/', methods=['GET'])
@jwt_required()
def list_banks():
    banks = QuestionBank.query.order_by(QuestionBank.created_at.desc()).all()
    return jsonify([bank_to_dict(b) for b in banks])


@banks_bp.route('/', methods=['POST'])
@jwt_required()
def create_bank():
    user = db.session.get(User, int(get_jwt_identity()))
    if not user:
        return jsonify({'error': '用户不存在，请重新登录'}), 401
    if not user.is_admin:
        return jsonify({'error': '需要管理员权限'}), 403
    data = request.get_json()
    bank = QuestionBank(name=data['name'], description=data.get('description', ''))
    db.session.add(bank)
    db.session.commit()
    return jsonify(bank_to_dict(bank)), 201


@banks_bp.route('/<int:bank_id>', methods=['PUT'])
@jwt_required()
def update_bank(bank_id):
    user = db.session.get(User, int(get_jwt_identity()))
    if not user:
        return jsonify({'error': '用户不存在，请重新登录'}), 401
    if not user.is_admin:
        return jsonify({'error': '需要管理员权限'}), 403
    bank = db.get_or_404(QuestionBank, bank_id)
    data = request.get_json()
    if 'name' in data:
        bank.name = data['name']
    if 'description' in data:
        bank.description = data['description']
    db.session.commit()
    return jsonify(bank_to_dict(bank))


@banks_bp.route('/<int:bank_id>', methods=['DELETE'])
@jwt_required()
def delete_bank(bank_id):
    user = db.session.get(User, int(get_jwt_identity()))
    if not user:
        return jsonify({'error': '用户不存在，请重新登录'}), 401
    if not user.is_admin:
        return jsonify({'error': '需要管理员权限'}), 403
    bank = db.get_or_404(QuestionBank, bank_id)
    try:
        question_ids_subquery = db.session.query(Question.id).filter(Question.bank_id == bank.id)

        QuizAnswer.query.filter(
            QuizAnswer.question_id.in_(question_ids_subquery)
        ).delete(synchronize_session=False)
        WrongAnswer.query.filter(
            WrongAnswer.question_id.in_(question_ids_subquery)
        ).delete(synchronize_session=False)

        QuizSession.query.filter_by(bank_id=bank.id).delete(synchronize_session=False)
        BankWordFrequency.query.filter_by(bank_id=bank.id).delete(synchronize_session=False)
        UserBankWordProgress.query.filter_by(bank_id=bank.id).delete(synchronize_session=False)
        BankWordExclusion.query.filter_by(bank_id=bank.id).delete(synchronize_session=False)
        Question.query.filter_by(bank_id=bank.id).delete(synchronize_session=False)

        db.session.delete(bank)
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({'error': '删除题库失败，请稍后重试'}), 500

    return jsonify({'message': '题库已删除'})


@banks_bp.route('/<int:bank_id>/import', methods=['POST'])
@jwt_required()
def import_questions(bank_id):
    user = db.session.get(User, int(get_jwt_identity()))
    if not user:
        return jsonify({'error': '用户不存在，请重新登录'}), 401
    if not user.is_admin:
        return jsonify({'error': '需要管理员权限'}), 403
    bank = db.get_or_404(QuestionBank, bank_id)

    if 'file' not in request.files:
        return jsonify({'error': '未上传文件'}), 400
    file = request.files['file']
    filename = file.filename.lower()

    try:
        questions_data = parse_file(file, filename)
    except Exception as e:
        return jsonify({'error': f'文件解析失败: {str(e)}'}), 400

    existing_questions = Question.query.filter_by(bank_id=bank.id).order_by(
        Question.order_index.asc(),
        Question.id.asc(),
    ).all()
    seen_signatures = {
        _question_signature(
            question.question_type,
            question.content,
            json.loads(question.options),
            question.correct_answer,
        )
        for question in existing_questions
    }
    next_order_index = max((question.order_index or 0 for question in existing_questions), default=-1) + 1

    count = 0
    missing_answer_count = 0
    skipped_duplicate_count = 0
    for q in questions_data:
        signature = _question_signature(
            q['question_type'],
            q['content'],
            q['options'],
            q['correct_answer'],
        )
        if signature in seen_signatures:
            skipped_duplicate_count += 1
            continue

        seen_signatures.add(signature)
        if q.get('answer_missing'):
            missing_answer_count += 1
        question = Question(
            bank_id=bank.id,
            question_type=q['question_type'],
            content=q['content'],
            options=json.dumps(q['options']),
            correct_answer=q['correct_answer'],
            order_index=next_order_index,
        )
        db.session.add(question)
        next_order_index += 1
        count += 1

    db.session.flush()

    full_bank_questions = Question.query.filter_by(bank_id=bank.id).order_by(Question.order_index.asc(), Question.id.asc()).all()
    frequency_items = build_bank_word_frequencies([
        {
            'content': question.content,
            'options': json.loads(question.options),
        }
        for question in full_bank_questions
    ])
    translated_frequency_items = translate_bank_word_frequencies(frequency_items)
    excluded_terms = {
        row.term
        for row in BankWordExclusion.query.filter_by(bank_id=bank.id).all()
    }
    BankWordFrequency.query.filter_by(bank_id=bank.id).delete()
    for item in translated_frequency_items:
        if item['term'] in excluded_terms:
            continue
        db.session.add(BankWordFrequency(
            bank_id=bank.id,
            term=item['term'],
            term_zh=item.get('term_zh'),
            frequency=item['frequency'],
        ))

    bank.question_count = len(full_bank_questions)
    bank.source_filename = file.filename
    invalidate_active_scope(
        build_scope_key(JOB_TYPE_BANK_FREQUENT_TRANSLATE, {'bank_id': bank.id}),
        '题库已重新导入，旧高频词翻译任务已失效',
    )
    db.session.commit()

    frequency_count = sum(
        1
        for item in translated_frequency_items
        if item['term'] not in excluded_terms and not item.get('term_zh')
    )
    msg = f'成功导入 {count} 道题目'
    if skipped_duplicate_count:
        msg += f'，跳过 {skipped_duplicate_count} 道重复题'
    if missing_answer_count:
        msg += f'，其中 {missing_answer_count} 道未找到正确答案（需手动补充）'
    return jsonify({
        'message': msg,
        'count': count,
        'missing_answer_count': missing_answer_count,
        'skipped_duplicate_count': skipped_duplicate_count,
        'frequency_count': frequency_count,
    })


@banks_bp.route('/<int:bank_id>/translate-frequencies', methods=['POST'])
@jwt_required()
def translate_frequencies(bank_id):
    user = db.session.get(User, int(get_jwt_identity()))
    if not user:
        return jsonify({'error': '用户不存在，请重新登录'}), 401
    if not user.is_admin:
        return jsonify({'error': '需要管理员权限'}), 403
    db.get_or_404(QuestionBank, bank_id)

    untranslated = BankWordFrequency.query.filter_by(
        bank_id=bank_id, term_zh=None
    ).order_by(BankWordFrequency.frequency.desc()).limit(100).all()

    if not untranslated:
        remaining = 0
        return jsonify({'translated': 0, 'remaining': remaining})

    batch = [{'term': item.term} for item in untranslated]
    translation_map = _translate_frequency_batch(batch, 1)

    translated_count = 0
    for index, item in enumerate(untranslated, start=1):
        zh = translation_map.get(index)
        if zh:
            item.term_zh = zh
            translated_count += 1

    db.session.commit()

    remaining = BankWordFrequency.query.filter_by(
        bank_id=bank_id, term_zh=None
    ).count()

    return jsonify({'translated': translated_count, 'remaining': remaining})
