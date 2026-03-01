from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from models import db, Vocabulary, User

vocab_bp = Blueprint('vocab', __name__)


@vocab_bp.route('/professional', methods=['GET'])
@jwt_required()
def list_professional():
    words = Vocabulary.query.filter_by(is_system=True)\
        .order_by(Vocabulary.term).all()
    return jsonify([_word_to_dict(w) for w in words])


@vocab_bp.route('/personal', methods=['GET'])
@jwt_required()
def list_personal():
    user_id = int(get_jwt_identity())
    words = Vocabulary.query.filter_by(user_id=user_id, is_system=False)\
        .order_by(Vocabulary.created_at.desc()).all()
    return jsonify([_word_to_dict(w) for w in words])


@vocab_bp.route('/personal', methods=['POST'])
@jwt_required()
def add_personal():
    user_id = int(get_jwt_identity())
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
        user_id=user_id,
    )
    db.session.add(word)
    db.session.commit()
    return jsonify(_word_to_dict(word)), 201


@vocab_bp.route('/personal/<int:word_id>', methods=['DELETE'])
@jwt_required()
def delete_personal(word_id):
    user_id = int(get_jwt_identity())
    word = Vocabulary.query.get_or_404(word_id)
    if word.user_id != user_id:
        return jsonify({'error': '无权限'}), 403
    db.session.delete(word)
    db.session.commit()
    return jsonify({'message': '已删除'})


@vocab_bp.route('/professional', methods=['POST'])
@jwt_required()
def add_professional():
    user_id = int(get_jwt_identity())
    user = User.query.get(user_id)
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
    return jsonify(_word_to_dict(word)), 201


@vocab_bp.route('/professional/<int:word_id>', methods=['DELETE'])
@jwt_required()
def delete_professional(word_id):
    user_id = int(get_jwt_identity())
    user = User.query.get(user_id)
    if not user or not user.is_admin:
        return jsonify({'error': '仅管理员可操作'}), 403

    word = Vocabulary.query.get_or_404(word_id)
    if not word.is_system:
        return jsonify({'error': '非专业词汇'}), 400
    db.session.delete(word)
    db.session.commit()
    return jsonify({'message': '已删除'})


@vocab_bp.route('/professional/batch-translate', methods=['POST'])
@jwt_required()
def batch_translate_professional():
    """批量翻译未翻译的专业词汇"""
    user_id = int(get_jwt_identity())
    user = User.query.get(user_id)
    if not user or not user.is_admin:
        return jsonify({'error': '仅管理员可操作'}), 403

    from services.ai_service import batch_translate_vocab

    # 查询所有未翻译的专业词汇
    untranslated = Vocabulary.query.filter(
        Vocabulary.is_system == True,
        Vocabulary.term_zh.is_(None)
    ).order_by(Vocabulary.term).all()

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
    user = User.query.get(user_id)
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


def _word_to_dict(w):
    return {
        'id': w.id,
        'term': w.term,
        'definition': w.definition,
        'term_zh': w.term_zh,
        'definition_zh': w.definition_zh,
        'is_system': w.is_system,
        'created_at': w.created_at.isoformat(),
    }
