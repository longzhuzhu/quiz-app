import json

import requests

from models import db, Question
from services.settings_service import get_effective_ai_settings


def _get_ai_config(scene='default'):
    """从数据库读取 AI 配置，回退到环境变量/默认值"""
    return get_effective_ai_settings(scene=scene)


def call_ai_api(messages, scene='default'):
    ai = _get_ai_config(scene=scene)
    if not ai['api_key']:
        raise ValueError('AI API Key 未配置，请在管理后台设置')

    base = ai['base_url'].rstrip('/')
    # 智能拼接：支持多种 Base URL 格式
    if base.endswith('/chat/completions'):
        api_url = base
    elif base.endswith('/v1'):
        api_url = base + '/chat/completions'
    else:
        api_url = base + '/v1/chat/completions'

    headers = {
        'Authorization': f'Bearer {ai["api_key"]}',
        'Content-Type': 'application/json',
    }
    payload = {
        'model': ai['model'],
        'messages': messages,
        'temperature': 0.3,
    }

    resp = requests.post(api_url, json=payload, headers=headers, timeout=60, verify=False)
    if not resp.ok:
        detail = resp.text[:200] if resp.text else resp.reason
        raise ValueError(f'AI API 错误 ({resp.status_code}): {detail}')
    data = resp.json()
    return data['choices'][0]['message']['content']


def translate_question(question):
    options = json.loads(question.options)
    options_text = '\n'.join([f"{o['key']}. {o['text']}" for o in options])

    messages = [
        {
            'role': 'system',
            'content': (
                '你是一位专业的隐私技术领域翻译专家。请将以下 CIPT 考试题目从英文翻译为中文。'
                '保留技术缩写（如 GDPR、PII、DPO、DPIA 等）不翻译。'
                '返回 JSON 格式：{"content_zh": "中文题目", "options_zh": [{"key": "A", "text_zh": "中文选项"}, ...]}'
                '只返回 JSON，不要其他内容。'
            ),
        },
        {
            'role': 'user',
            'content': f'题目：{question.content}\n\n选项：\n{options_text}',
        },
    ]

    result_text = call_ai_api(messages, scene='translate')
    result_text = result_text.strip()
    if result_text.startswith('```'):
        result_text = result_text.split('\n', 1)[1]
        result_text = result_text.rsplit('```', 1)[0]

    result = json.loads(result_text)

    question.content_zh = result['content_zh']
    for opt in options:
        for opt_zh in result['options_zh']:
            if opt['key'] == opt_zh['key']:
                opt['text_zh'] = opt_zh['text_zh']
                break
    question.options = json.dumps(options, ensure_ascii=False)
    db.session.commit()

    return result


def translate_term(term):
    """翻译单个术语/短语，返回中文翻译和释义"""
    messages = [
        {
            'role': 'system',
            'content': (
                '你是一位专业的隐私技术领域翻译专家。'
                '请将以下英文术语或短语翻译为中文，并提供简短的中文释义。'
                '返回 JSON 格式：{"term_zh": "中文翻译", "definition_zh": "中文释义"}'
                '只返回 JSON，不要其他内容。'
            ),
        },
        {
            'role': 'user',
            'content': term,
        },
    ]

    result_text = call_ai_api(messages, scene='translate')
    result_text = result_text.strip()
    if result_text.startswith('```'):
        result_text = result_text.split('\n', 1)[1]
        result_text = result_text.rsplit('```', 1)[0]

    return json.loads(result_text)


def batch_translate_vocab(vocab_list):
    """批量翻译词汇，每次最多 20 个术语

    vocab_list: Vocabulary 对象列表（需要有 term 和 definition）
    返回成功翻译的数量
    """
    terms_data = []
    for v in vocab_list:
        entry = {'id': v.id, 'term': v.term}
        if v.definition:
            entry['definition'] = v.definition
        terms_data.append(entry)

    results = batch_translate_terms(terms_data)
    result_map = {r['id']: r for r in results}

    count = 0
    for v in vocab_list:
        r = result_map.get(v.id)
        if r:
            v.term_zh = r.get('term_zh') or v.term_zh
            v.definition_zh = r.get('definition_zh') or v.definition_zh
            count += 1

    db.session.commit()
    return count


def batch_translate_terms(terms_data):
    terms_json = json.dumps(terms_data, ensure_ascii=False)
    messages = [
        {
            'role': 'system',
            'content': (
                '你是一位专业的隐私技术领域翻译专家。'
                '请将以下隐私/数据保护领域的英文术语翻译为中文。'
                '对每个术语提供：term_zh（术语的中文翻译）和 definition_zh（释义的中文翻译，如有英文释义的话）。'
                '技术缩写（如 GDPR、APEC、DPO 等）保留原文不翻译。'
                '返回 JSON 数组格式：[{"id": 1, "term_zh": "中文翻译", "definition_zh": "中文释义"}, ...]'
                '只返回 JSON 数组，不要其他内容。'
            ),
        },
        {
            'role': 'user',
            'content': terms_json,
        },
    ]

    result_text = call_ai_api(messages, scene='translate')
    result_text = result_text.strip()
    if result_text.startswith('```'):
        result_text = result_text.split('\n', 1)[1]
        result_text = result_text.rsplit('```', 1)[0]

    return json.loads(result_text)


def explain_question(question):
    options = json.loads(question.options)
    options_text = '\n'.join([f"{o['key']}. {o['text']}" for o in options])

    messages = [
        {
            'role': 'system',
            'content': (
                '你是一位 CIPT（认证信息隐私技术师）考试辅导专家。'
                '请解析以下题目，说明正确答案的原因以及其他选项为什么不正确。'
                '返回 JSON 格式：{"explanation": "英文解析", "explanation_zh": "中文解析"}'
                '只返回 JSON，不要其他内容。'
            ),
        },
        {
            'role': 'user',
            'content': f'题目：{question.content}\n\n选项：\n{options_text}\n\n正确答案：{question.correct_answer}',
        },
    ]

    result_text = call_ai_api(messages, scene='explain')
    result_text = result_text.strip()
    if result_text.startswith('```'):
        result_text = result_text.split('\n', 1)[1]
        result_text = result_text.rsplit('```', 1)[0]

    result = json.loads(result_text)

    question.explanation = result['explanation']
    question.explanation_zh = result['explanation_zh']
    db.session.commit()

    return result
