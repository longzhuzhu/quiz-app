from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from math import ceil

from models import (
    db,
    Vocabulary,
    User,
    QuestionBank,
    BankWordFrequency,
    UserVocabProgress,
    UserBankWordProgress,
    BankWordExclusion,
)
from services.import_service import MIN_FREQUENCY, TOP_FREQUENT_TERMS_LIMIT
from services.job_service import list_bank_frequent_terms, text_missing, vocabulary_needs_translation

vocab_bp = Blueprint('vocab', __name__)


def word_needs_translation(word):
    return vocabulary_needs_translation(word)


@vocab_bp.route('/professional', methods=['GET'])
@jwt_required()
def list_professional():
    user, error = _require_current_user()
    if error:
        return error
    words = Vocabulary.query.filter_by(is_system=True)\
        .order_by(Vocabulary.term).all()
    progress_by_vocab_id = _get_progress_map(user.id)
    mastered_filter = request.args.get('mastered')
    if mastered_filter is not None:
        mastered_value = _parse_bool_arg(mastered_filter)
        if mastered_value is None:
            return jsonify({'error': 'mastered 参数无效'}), 400
        words = [
            word for word in words
            if progress_by_vocab_id.get(word.id, False) is mastered_value
        ]
    return jsonify([_word_to_dict(w, user, progress_by_vocab_id) for w in words])


@vocab_bp.route('/personal', methods=['GET'])
@jwt_required()
def list_personal():
    user, error = _require_current_user()
    if error:
        return error
    words = Vocabulary.query.filter_by(user_id=user.id, is_system=False)\
        .order_by(Vocabulary.created_at.desc()).all()
    progress_by_vocab_id = _get_progress_map(user.id)
    mastered_filter = request.args.get('mastered')
    if mastered_filter is not None:
        mastered_value = _parse_bool_arg(mastered_filter)
        if mastered_value is None:
            return jsonify({'error': 'mastered 参数无效'}), 400
        words = [
            word for word in words
            if progress_by_vocab_id.get(word.id, False) is mastered_value
        ]
    return jsonify([_word_to_dict(w, user, progress_by_vocab_id) for w in words])


@vocab_bp.route('/personal', methods=['POST'])
@jwt_required()
def add_personal():
    user, error = _require_current_user()
    if error:
        return error
    data = request.get_json()
    term = data.get('term', '').strip()
    if not term:
        return jsonify({'error': '单词不能为空'}), 400

    term_zh = data.get('term_zh', '').strip() or None
    definition_zh = data.get('definition_zh', '').strip() or None

    # 自动翻译：未提供中文时调用 AI
    if data.get('auto_translate') and not term_zh:
        try:
            from services.ai_service import translate_term
            result = translate_term(term)
            term_zh = result.get('term_zh') or term_zh
            definition_zh = result.get('definition_zh') or definition_zh
        except Exception:
            pass  # 翻译失败不影响保存

    word = Vocabulary(
        term=term,
        definition=data.get('definition', '').strip() or None,
        term_zh=term_zh,
        definition_zh=definition_zh,
        is_system=False,
        user_id=user.id,
    )
    db.session.add(word)
    db.session.commit()
    return jsonify(_word_to_dict(word, user, {})), 201


@vocab_bp.route('/items/<int:vocabulary_id>/progress', methods=['PUT'])
@jwt_required()
def update_progress(vocabulary_id):
    user, error = _require_current_user()
    if error:
        return error
    word = db.get_or_404(Vocabulary, vocabulary_id)
    data = request.get_json() or {}
    is_mastered = data.get('is_mastered')
    if not isinstance(is_mastered, bool):
        return jsonify({'error': 'is_mastered 必须为布尔值'}), 400
    if not word.is_system and word.user_id != user.id:
        return jsonify({'error': '无权限'}), 403

    progress = UserVocabProgress.query.filter_by(
        user_id=user.id,
        vocabulary_id=word.id,
    ).first()
    if progress is None:
        progress = UserVocabProgress(
            user_id=user.id,
            vocabulary_id=word.id,
            is_mastered=is_mastered,
        )
        db.session.add(progress)
    else:
        progress.is_mastered = is_mastered

    db.session.commit()
    return jsonify({'message': '已标记为掌握' if is_mastered else '已取消掌握'})


@vocab_bp.route('/professional', methods=['POST'])
@jwt_required()
def add_professional():
    user, error = _require_current_user()
    if error:
        return error
    if not user or not user.is_admin:
        return jsonify({'error': '仅管理员可操作'}), 403

    data = request.get_json()
    term = data.get('term', '').strip()
    if not term:
        return jsonify({'error': '单词不能为空'}), 400

    word = Vocabulary(
        term=term,
        definition=data.get('definition', '').strip() or None,
        term_zh=data.get('term_zh', '').strip() or None,
        definition_zh=data.get('definition_zh', '').strip() or None,
        is_system=True,
    )
    db.session.add(word)
    db.session.commit()
    return jsonify(_word_to_dict(word, user, {})), 201


@vocab_bp.route('/items/<int:vocabulary_id>', methods=['DELETE'])
@jwt_required()
def delete_vocab_item(vocabulary_id):
    user, error = _require_current_user()
    if error:
        return error
    if not user or not user.is_admin:
        return jsonify({'error': '仅管理员可操作'}), 403

    word = db.get_or_404(Vocabulary, vocabulary_id)
    UserVocabProgress.query.filter_by(vocabulary_id=word.id).delete(synchronize_session=False)
    db.session.delete(word)
    db.session.commit()
    return jsonify({'message': '已删除'})


@vocab_bp.route('/personal/<int:word_id>', methods=['DELETE'])
@jwt_required()
def delete_personal(word_id):
    user, error = _require_current_user()
    if error:
        return error
    if not user or not user.is_admin:
        return jsonify({'error': '仅管理员可操作'}), 403

    word = db.get_or_404(Vocabulary, word_id)
    if word.is_system:
        return jsonify({'error': '非个人词汇'}), 400

    return delete_vocab_item(word_id)


@vocab_bp.route('/professional/<int:word_id>', methods=['DELETE'])
@jwt_required()
def delete_professional(word_id):
    user, error = _require_current_user()
    if error:
        return error
    if not user or not user.is_admin:
        return jsonify({'error': '仅管理员可操作'}), 403

    word = db.get_or_404(Vocabulary, word_id)
    if not word.is_system:
        return jsonify({'error': '非专业词汇'}), 400

    UserVocabProgress.query.filter_by(vocabulary_id=word.id).delete(synchronize_session=False)
    db.session.delete(word)
    db.session.commit()
    return jsonify({'message': '已删除'})


@vocab_bp.route('/professional/batch-translate', methods=['POST'])
@jwt_required()
def batch_translate_professional():
    """批量翻译未翻译的专业词汇"""
    user_id = int(get_jwt_identity())
    user = db.session.get(User, user_id)
    if not user or not user.is_admin:
        return jsonify({'error': '仅管理员可操作'}), 403

    from services.ai_service import batch_translate_vocab

    # 查询所有未翻译的专业词汇
    untranslated = [
        word for word in Vocabulary.query.filter(Vocabulary.is_system.is_(True)).order_by(Vocabulary.term).all()
        if word_needs_translation(word)
    ]

    if not untranslated:
        return jsonify({'message': '所有词汇已翻译', 'translated': 0, 'remaining': 0})

    batch_size = 10
    batch = untranslated[:batch_size]
    translated = 0
    try:
        translated = batch_translate_vocab(batch)
    except Exception as e:
        # 部分成功也保留
        db.session.rollback()
        return jsonify({
            'error': f'翻译出错：{str(e)}',
            'translated': 0,
            'remaining': len(untranslated),
        }), 500

    remaining = len(untranslated) - translated
    return jsonify({
        'message': f'本次翻译 {translated} 个，剩余 {remaining} 个',
        'translated': translated,
        'remaining': remaining,
    })


@vocab_bp.route('/professional/import-iapp', methods=['POST'])
@jwt_required()
def import_iapp_glossary():
    """从 IAPP 网站批量导入隐私专业词汇"""
    user_id = int(get_jwt_identity())
    user = db.session.get(User, user_id)
    if not user or not user.is_admin:
        return jsonify({'error': '仅管理员可操作'}), 403

    try:
        from scripts.import_iapp_glossary import fetch_glossary_terms, import_terms
        terms = fetch_glossary_terms()
        added, skipped = import_terms(terms)
        return jsonify({
            'message': f'导入完成：新增 {added} 个，跳过 {skipped} 个已存在术语',
            'added': added,
            'skipped': skipped,
            'total_fetched': len(terms),
        })
    except Exception as e:
        return jsonify({'error': f'导入失败：{str(e)}'}), 500


@vocab_bp.route('/frequent', methods=['GET'])
@jwt_required()
def list_frequent():
    user, error = _require_current_user()
    if error:
        return error
    bank_id = request.args.get('bank_id', type=int)
    if not bank_id:
        return jsonify({'error': '缺少 bank_id 参数'}), 400

    bank = db.session.get(QuestionBank, bank_id)
    if not bank:
        return jsonify({'error': '题库不存在'}), 404

    page = request.args.get('page', default=1, type=int) or 1
    per_page = request.args.get('per_page', default=50, type=int) or 50
    page = max(1, page)
    per_page = max(1, min(per_page, 100))

    progress_by_term = _get_bank_word_progress_map(user.id, bank_id)
    mastered_filter = request.args.get('mastered')
    mastered_value = None
    if mastered_filter is not None:
        mastered_value = _parse_bool_arg(mastered_filter)
        if mastered_value is None:
            return jsonify({'error': 'mastered 参数无效'}), 400
    top_terms = list_bank_frequent_terms(bank_id)
    visible_terms = top_terms
    if mastered_value is not None:
        visible_terms = [
            item for item in visible_terms
            if progress_by_term.get(item.term, False) is mastered_value
        ]

    untranslated_terms = sum(1 for item in visible_terms if text_missing(item.term_zh))
    total_terms = len(visible_terms)
    total_pages = max(1, ceil(total_terms / per_page)) if total_terms else 1
    start = (page - 1) * per_page
    end = start + per_page
    items = visible_terms[start:end]

    return jsonify({
        'bank': {'id': bank.id, 'name': bank.name},
        'summary': {
            'total_terms': total_terms,
            'untranslated_terms': untranslated_terms,
            'min_frequency': MIN_FREQUENCY,
            'top_terms_limit': TOP_FREQUENT_TERMS_LIMIT,
        },
        'pagination': {
            'page': page,
            'per_page': per_page,
            'total_pages': total_pages,
            'total_items': total_terms,
        },
        'items': [
            {
                'term': item.term,
                'term_zh': item.term_zh,
                'frequency': item.frequency,
                'is_mastered': progress_by_term.get(item.term, False),
                'can_delete': bool(user and user.is_admin),
                'can_mark_mastered': True,
            }
            for item in items
        ],
    })


@vocab_bp.route('/frequent-items/progress', methods=['PUT'])
@jwt_required()
def update_frequent_progress():
    user, error = _require_current_user()
    if error:
        return error
    data = request.get_json() or {}
    bank_id = data.get('bank_id')
    term = (data.get('term') or '').strip()
    is_mastered = data.get('is_mastered')

    if not isinstance(bank_id, int):
        return jsonify({'error': 'bank_id 必须为整数'}), 400
    if not term:
        return jsonify({'error': 'term 不能为空'}), 400
    if not isinstance(is_mastered, bool):
        return jsonify({'error': 'is_mastered 必须为布尔值'}), 400

    bank = db.session.get(QuestionBank, bank_id)
    if not bank:
        return jsonify({'error': '题库不存在'}), 404

    excluded = BankWordExclusion.query.filter_by(bank_id=bank_id, term=term).first()
    if excluded:
        return jsonify({'error': '词条已被排除'}), 404

    frequency_item = BankWordFrequency.query.filter_by(bank_id=bank_id, term=term).first()
    if not frequency_item:
        return jsonify({'error': '词条不存在'}), 404

    progress = UserBankWordProgress.query.filter_by(
        user_id=user.id,
        bank_id=bank_id,
        term=term,
    ).first()
    if progress is None:
        progress = UserBankWordProgress(
            user_id=user.id,
            bank_id=bank_id,
            term=term,
            is_mastered=is_mastered,
        )
        db.session.add(progress)
    else:
        progress.is_mastered = is_mastered

    db.session.commit()
    return jsonify({'message': '已标记为掌握' if is_mastered else '已取消掌握'})


@vocab_bp.route('/frequent-items', methods=['DELETE'])
@jwt_required()
def exclude_frequent_item():
    user, error = _require_current_user()
    if error:
        return error
    if not user or not user.is_admin:
        return jsonify({'error': '仅管理员可操作'}), 403

    bank_id = request.args.get('bank_id', type=int)
    term = (request.args.get('term') or '').strip()
    if not bank_id:
        return jsonify({'error': '缺少 bank_id 参数'}), 400
    if not term:
        return jsonify({'error': '缺少 term 参数'}), 400

    bank = db.session.get(QuestionBank, bank_id)
    if not bank:
        return jsonify({'error': '题库不存在'}), 404

    frequency_item = BankWordFrequency.query.filter_by(bank_id=bank_id, term=term).first()
    excluded = BankWordExclusion.query.filter_by(bank_id=bank_id, term=term).first()
    if frequency_item is None and excluded is None:
        return jsonify({'error': '词条不存在'}), 404
    if excluded is None:
        db.session.add(BankWordExclusion(bank_id=bank_id, term=term, created_by=user.id))

    if frequency_item is not None:
        db.session.delete(frequency_item)
    db.session.commit()
    return jsonify({'message': '已删除'})


@vocab_bp.route('/stats', methods=['GET'])
@jwt_required()
def vocab_stats():
    user_id = int(get_jwt_identity())
    professional_count = Vocabulary.query.filter_by(is_system=True).count()
    personal_count = Vocabulary.query.filter_by(user_id=user_id, is_system=False).count()
    return jsonify({
        'professional': professional_count,
        'personal': personal_count,
    })


def _word_to_dict(w, user, progress_by_vocab_id):
    return {
        'id': w.id,
        'term': w.term,
        'definition': w.definition,
        'term_zh': w.term_zh,
        'definition_zh': w.definition_zh,
        'is_system': w.is_system,
        'is_mastered': progress_by_vocab_id.get(w.id, False),
        'can_delete': bool(user and user.is_admin),
        'can_mark_mastered': True,
        'created_at': w.created_at.isoformat(),
    }


def _get_current_user():
    user_id = int(get_jwt_identity())
    return db.session.get(User, user_id)


def _require_current_user():
    user = _get_current_user()
    if user is None:
        return None, (jsonify({'error': '用户不存在或登录已失效'}), 401)
    return user, None


def _get_progress_map(user_id):
    progress_rows = UserVocabProgress.query.filter_by(user_id=user_id).all()
    return {row.vocabulary_id: row.is_mastered for row in progress_rows}


def _get_bank_word_progress_map(user_id, bank_id):
    progress_rows = UserBankWordProgress.query.filter_by(user_id=user_id, bank_id=bank_id).all()
    return {row.term: row.is_mastered for row in progress_rows}


def _get_excluded_term_set(bank_id):
    exclusion_rows = BankWordExclusion.query.filter_by(bank_id=bank_id).all()
    return {row.term for row in exclusion_rows}


def _parse_bool_arg(value):
    normalized = str(value).strip().lower()
    if normalized in {'true', '1', 'yes'}:
        return True
    if normalized in {'false', '0', 'no'}:
        return False
    return None
