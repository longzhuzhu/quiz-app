"""AI 服务 - 翻译、解析、术语翻译（适配 FastAPI + SQLAlchemy 2.x）"""

import json

import httpx

from sqlalchemy.orm.attributes import flag_modified

from app.models.question import Question
from app.services.exam_service import DEFAULT_EXPLANATION_SYSTEM_PROMPT, DEFAULT_TRANSLATION_SYSTEM_PROMPT
from app.services.settings_service import get_effective_ai_settings, validate_ai_base_url


SECTION_STEM_BREAKDOWN = "【题干拆解】"
SECTION_ANSWER_ANALYSIS = "【知识点解析】"
SECTION_DISTRACTORS = "【干扰项分析】"

STEM_BREAKDOWN_LABELS = (
    ("qualifier", "限定词"),
    ("role", "角色"),
    ("scenario", "场景"),
    ("constraint", "约束"),
    ("asked", "问的是什么"),
)


def _load_options(question: Question) -> list:
    options = question.options
    if isinstance(options, str):
        return json.loads(options)
    return options


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0]
    return text


def has_question_translation(question: Question) -> bool:
    if not question.content_zh:
        return False
    options = _load_options(question)
    return all(opt.get("text_zh") for opt in options)


def has_question_explanation(question: Question) -> bool:
    return bool(question.explanation or question.explanation_zh)


def build_question_translation_payload(question: Question) -> dict:
    options = _load_options(question)
    options_zh = []
    for option in options:
        if option.get("text_zh"):
            options_zh.append({"key": option["key"], "text_zh": option["text_zh"]})
    return {
        "content_zh": question.content_zh,
        "options_zh": options_zh,
    }


def build_question_explanation_payload(question: Question) -> dict:
    return {
        "explanation": question.explanation,
        "explanation_zh": question.explanation_zh,
    }


def clear_question_translation(db, question: Question):
    question.content_zh = None
    options = _load_options(question)
    for option in options:
        option.pop("text_zh", None)
    question.options = options  # JSONB 整字段重赋值
    flag_modified(question, "options")  # PostgreSQL JSONB 需显式标记脏


def clear_question_explanation(db, question: Question):
    question.explanation = None
    question.explanation_zh = None


def sanitize_options_for_storage(options):
    return [{k: v for k, v in option.items() if k != "text_zh"} for option in options]


def call_ai_api(messages, db, scene: str = "default", timeout: float = 60.0):
    """调用 AI Chat Completion API（OpenAI 兼容协议）。

    参数:
        messages: OpenAI 兼容的 messages 列表（list[{"role": ..., "content": ...}])
        db: SQLAlchemy Session，用于读取 SystemSetting 中的 AI 配置
        scene: AI 场景标识（"default" / "translate" / "explain" / "smart_import"），
            用于按场景选择不同的 model 配置。
        timeout: HTTP 请求超时秒数。默认 60.0；smart_import 等异步重 chunk
            场景应显式传 120.0。该值直接透传给 httpx.post 的 timeout 参数
            （对连接 + 读 + 写都生效）。

    返回:
        str: LLM 响应中 ``choices[0].message.content`` 字段。

    抛出:
        ValueError: API Key 未配置，或 API 返回非 2xx 状态码。
        httpx.TimeoutException: 请求超时（含 ConnectTimeout / ReadTimeout 等）。
            注意：本函数**不**对超时做 wrap，原生异常直接冒泡，调用方可
            ``except httpx.TimeoutException`` 精准捕获并按需重试。
        httpx.HTTPError: 其它 httpx 层错误（连接拒绝、SSL 等）。
    """
    ai = get_effective_ai_settings(db, scene=scene)
    if not ai["api_key"]:
        raise ValueError("AI API Key 未配置，请在管理后台设置")

    base = ai["base_url"].rstrip("/")
    # 智能拼接：支持多种 Base URL 格式
    if base.endswith("/chat/completions"):
        api_url = base
    elif base.endswith("/v1"):
        api_url = base + "/chat/completions"
    else:
        api_url = base + "/v1/chat/completions"

    headers = {
        "Authorization": f'Bearer {ai["api_key"]}',
        "Content-Type": "application/json",
    }
    payload = {
        "model": ai["model"],
        "messages": messages,
        "temperature": 0.3,
    }

    resp = httpx.post(api_url, json=payload, headers=headers, timeout=timeout, verify=True)
    if not resp.is_success:
        detail = resp.text[:200] if resp.text else resp.reason_phrase
        raise ValueError(f"AI API 错误 ({resp.status_code}): {detail}")
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def _exam_ai_profile(question: Question) -> dict:
    if question.bank and question.bank.exam:
        return question.bank.exam.ai_profile or {}
    return {}


def translate_question(db, question: Question) -> dict:
    options = _load_options(question)
    options_text = "\n".join([f"{o['key']}. {o['text']}" for o in options])
    ai_profile = _exam_ai_profile(question)

    messages = [
        {
            "role": "system",
            "content": ai_profile.get("translation_system_prompt") or DEFAULT_TRANSLATION_SYSTEM_PROMPT,
        },
        {
            "role": "user",
            "content": f"题目：{question.content}\n\n选项：\n{options_text}",
        },
    ]

    result_text = _strip_code_fence(call_ai_api(messages, db, scene="translate"))
    result = json.loads(result_text)

    question.content_zh = result["content_zh"]
    for opt in options:
        for opt_zh in result["options_zh"]:
            if opt["key"] == opt_zh["key"]:
                opt["text_zh"] = opt_zh["text_zh"]
                break
    question.options = options  # JSONB 整字段重赋值
    flag_modified(question, "options")  # PostgreSQL JSONB 需显式标记脏
    db.commit()

    return build_question_translation_payload(question)


def translate_term(term: str, db=None) -> dict:
    """翻译单个术语"""
    if db:
        ai = get_effective_ai_settings(db, scene="translate")
        base_url = ai["base_url"]
        api_key = ai["api_key"]
        model = ai["model"]
    else:
        from app.core.config import settings

        base_url = validate_ai_base_url(settings.AI_API_BASE_URL)
        api_key = settings.AI_API_KEY
        model = settings.AI_MODEL

    if not api_key:
        raise ValueError("AI API Key 未配置")

    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        api_url = base
    elif base.endswith("/v1"):
        api_url = base + "/chat/completions"
    else:
        api_url = base + "/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    messages = [
        {
            "role": "system",
            "content": (
                "你是一位专业的隐私技术领域翻译专家。"
                "请将以下英文术语或短语翻译为中文，并提供简短的中文释义。"
                '返回 JSON 格式：{"term_zh": "中文翻译", "definition_zh": "中文释义"}'
                "只返回 JSON，不要其他内容。"
            ),
        },
        {
            "role": "user",
            "content": term,
        },
    ]

    payload = {"model": model, "messages": messages, "temperature": 0.3}
    resp = httpx.post(api_url, json=payload, headers=headers, timeout=60.0, verify=True)
    if not resp.is_success:
        raise ValueError(f"AI API 错误: {resp.status_code}")

    result_text = resp.json()["choices"][0]["message"]["content"]
    result_text = _strip_code_fence(result_text)
    return json.loads(result_text)


def batch_translate_vocab(db, vocab_list) -> int:
    """批量翻译词汇，返回成功翻译的数量"""
    from app.models.vocabulary import Vocabulary

    terms_data = []
    for v in vocab_list:
        entry = {"id": v.id, "term": v.term}
        if v.definition:
            entry["definition"] = v.definition
        terms_data.append(entry)

    results = batch_translate_terms(terms_data, db)
    result_map = {r["id"]: r for r in results}

    count = 0
    for v in vocab_list:
        r = result_map.get(v.id)
        if r:
            v.term_zh = r.get("term_zh") or v.term_zh
            v.definition_zh = r.get("definition_zh") or v.definition_zh
            count += 1

    db.commit()
    return count


def batch_translate_terms(terms_data, db=None) -> list:
    terms_json = json.dumps(terms_data, ensure_ascii=False)
    messages = [
        {
            "role": "system",
            "content": (
                "你是一位专业的隐私技术领域翻译专家。"
                "请将以下隐私/数据保护领域的英文术语翻译为中文。"
                "对每个术语提供：term_zh（术语的中文翻译）和 definition_zh（释义的中文翻译，如有英文释义的话）。"
                "技术缩写（如 GDPR、APEC、DPO 等）保留原文不翻译。"
                '返回 JSON 数组格式：[{"id": 1, "term_zh": "中文翻译", "definition_zh": "中文释义"}, ...]'
                "只返回 JSON 数组，不要其他内容。"
            ),
        },
        {
            "role": "user",
            "content": terms_json,
        },
    ]

    result_text = call_ai_api(messages, db, scene="translate")
    result_text = result_text.strip()
    if result_text.startswith("```"):
        result_text = result_text.split("\n", 1)[1]
        result_text = result_text.rsplit("```", 1)[0]

    return json.loads(result_text)


def _clean_text(value) -> str:
    if isinstance(value, str):
        return value.strip()
    # LLM 偶尔把选项 key 返回成数字；bool 是 int 子类，必须排除
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return ""


def _render_stem_breakdown(breakdown) -> str:
    if not isinstance(breakdown, dict):
        return ""
    lines = [
        f"{label}：{text}"
        for key, label in STEM_BREAKDOWN_LABELS
        if (text := _clean_text(breakdown.get(key)))
    ]
    if not lines:
        return ""
    return "\n".join([SECTION_STEM_BREAKDOWN, *lines])


def _render_distractors(distractors) -> str:
    if not isinstance(distractors, list):
        return ""
    lines = []
    for item in distractors:
        if not isinstance(item, dict):
            continue
        key = _clean_text(item.get("key"))
        distractor_type = _clean_text(item.get("type"))
        reason = _clean_text(item.get("reason"))
        head = f"{key}（{distractor_type}）" if key and distractor_type else key or distractor_type
        if not head and not reason:
            continue
        lines.append(f"{head}：{reason}" if head and reason else head or reason)
    if not lines:
        return ""
    return "\n".join([SECTION_DISTRACTORS, *lines])


def compose_explanation_zh(result: dict) -> str:
    """把 LLM 返回的结构化解析组装成分段中文文本。

    版式由服务端控制而不是让 LLM 自己拼，输出才稳定。
    ``stem_breakdown`` 和 ``distractors`` 都缺失时（自定义 prompt 仍返回旧的
    两键结构），原样返回 ``explanation_zh``，保持改动前的行为。
    """
    answer_analysis = _clean_text(result.get("explanation_zh"))
    stem_breakdown = _render_stem_breakdown(result.get("stem_breakdown"))
    distractors = _render_distractors(result.get("distractors"))

    if not stem_breakdown and not distractors:
        return answer_analysis

    sections = []
    if stem_breakdown:
        sections.append(stem_breakdown)
    if answer_analysis:
        sections.append(f"{SECTION_ANSWER_ANALYSIS}\n{answer_analysis}")
    if distractors:
        sections.append(distractors)
    return "\n\n".join(sections)


def explain_question(db, question: Question) -> dict:
    options = _load_options(question)
    options_text = "\n".join([f"{o['key']}. {o['text']}" for o in options])
    ai_profile = _exam_ai_profile(question)

    messages = [
        {
            "role": "system",
            "content": ai_profile.get("explanation_system_prompt") or DEFAULT_EXPLANATION_SYSTEM_PROMPT,
        },
        {
            "role": "user",
            "content": f"题目：{question.content}\n\n选项：\n{options_text}\n\n正确答案：{question.correct_answer}",
        },
    ]

    result_text = _strip_code_fence(call_ai_api(messages, db, scene="explain"))
    result = json.loads(result_text)

    explanation = _clean_text(result.get("explanation"))
    explanation_zh = compose_explanation_zh(result)
    if not explanation and not explanation_zh:
        raise ValueError("AI 未返回解析内容")

    question.explanation = explanation or None
    question.explanation_zh = explanation_zh or None
    db.commit()

    return build_question_explanation_payload(question)
