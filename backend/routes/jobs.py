from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from models import BackgroundJob, QuestionBank, User, db
from services.job_service import (
    JOB_TYPE_BANK_FREQUENT_TRANSLATE,
    JOB_TYPE_PROFESSIONAL_VOCAB_TRANSLATE,
    JobServiceError,
    build_scope_key,
    create_or_reuse_job,
    serialize_job,
)

jobs_bp = Blueprint('jobs', __name__)


VALID_JOB_TYPES = {
    JOB_TYPE_PROFESSIONAL_VOCAB_TRANSLATE,
    JOB_TYPE_BANK_FREQUENT_TRANSLATE,
}


def _require_admin():
    user = db.session.get(User, int(get_jwt_identity()))
    if not user:
        return None, (jsonify({'error': '用户不存在，请重新登录'}), 401)
    if not user.is_admin:
        return None, (jsonify({'error': '仅管理员可操作'}), 403)
    return user, None


def _parse_bank_id(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _build_payload(job_type, source):
    payload = {}
    if job_type == JOB_TYPE_BANK_FREQUENT_TRANSLATE:
        bank_id = _parse_bank_id(source.get('bank_id'))
        if bank_id is None:
            return None, (jsonify({'error': 'bank_id 必须为整数'}), 400)
        bank = db.session.get(QuestionBank, bank_id)
        if not bank:
            return None, (jsonify({'error': '题库不存在'}), 404)
        payload['bank_id'] = bank_id
    return payload, None


@jobs_bp.route('', methods=['POST'])
@jwt_required()
def create_job():
    user, error = _require_admin()
    if error:
        return error

    data = request.get_json(silent=True) or {}
    job_type = data.get('job_type')
    if job_type not in VALID_JOB_TYPES:
        return jsonify({'error': '不支持的任务类型'}), 400

    payload, payload_error = _build_payload(job_type, data)
    if payload_error:
        return payload_error

    try:
        result, job, message = create_or_reuse_job(job_type, payload, user.id)
    except JobServiceError as exc:
        return jsonify({'error': exc.message}), exc.status_code
    status_code = 201 if result == 'created' else 200
    return jsonify({'result': result, 'job': serialize_job(job) if job else None, 'message': message}), status_code


@jobs_bp.route('/<int:job_id>', methods=['GET'])
@jwt_required()
def get_job(job_id):
    _user, error = _require_admin()
    if error:
        return error
    job = db.get_or_404(BackgroundJob, job_id)
    return jsonify({'job': serialize_job(job)})


@jobs_bp.route('/active', methods=['GET'])
@jwt_required()
def get_active_job():
    _user, error = _require_admin()
    if error:
        return error

    job_type = request.args.get('job_type')
    if job_type not in VALID_JOB_TYPES:
        return jsonify({'error': '不支持的任务类型'}), 400

    payload, payload_error = _build_payload(job_type, request.args)
    if payload_error:
        return payload_error

    scope_key = build_scope_key(job_type, payload)
    job = BackgroundJob.query.filter_by(active_scope_key=scope_key).order_by(BackgroundJob.id.desc()).first()
    return jsonify({'job': serialize_job(job) if job else None})
