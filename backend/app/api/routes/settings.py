"""Settings API 路由 - AI 配置管理、连接测试"""

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.database import get_db
from app.models.user import User
from app.schemas.settings import AISettingsUpdateRequest, AITestRequest, QuizSettingsUpdateRequest
from app.services.ai_service import build_chat_completion_payload
from app.services.settings_service import (
    QUIZ_AI_PREWARM_ENABLED_SETTING,
    EXPLANATION_MODELS_SETTING,
    WRONG_MASTERY_CORRECT_STREAK_MAX,
    WRONG_MASTERY_CORRECT_STREAK_MIN,
    WRONG_MASTERY_CORRECT_STREAK_SETTING,
    get_explanation_models,
    get_effective_ai_settings,
    get_key as get_setting,
    get_masked_effective_ai_api_key,
    get_wrong_mastery_correct_streak,
    has_effective_ai_api_key,
    get_effective_ai_api_key,
    is_quiz_ai_prewarm_enabled,
    set_bool_key,
    set_encrypted_ai_api_key,
    set_key as set_setting,
    validate_ai_base_url,
)

router = APIRouter()

AI_SETTING_KEYS = [
    "ai_api_base_url",
    "ai_api_key",
    "ai_model",
    "ai_translate_model",
    "ai_explain_model",
]


@router.get("/ai")
def get_ai_settings(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return {
        "ai_api_base_url": get_setting(db, "ai_api_base_url", ""),
        "ai_api_key": get_masked_effective_ai_api_key(db),
        "ai_api_key_configured": has_effective_ai_api_key(db),
        "ai_model": get_setting(db, "ai_model", ""),
        "ai_translate_model": get_setting(db, "ai_translate_model", ""),
        "ai_explain_model": get_setting(db, "ai_explain_model", ""),
        "ai_explain_models": [item.model_dump() for item in get_explanation_models(db)],
    }


@router.put("/ai")
def update_ai_settings(
    data: AISettingsUpdateRequest,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if data.ai_api_base_url is not None:
        try:
            set_setting(db, "ai_api_base_url", validate_ai_base_url(data.ai_api_base_url))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    api_key = (data.ai_api_key or "").strip()
    if api_key:
        set_encrypted_ai_api_key(db, api_key)
    if data.ai_model is not None:
        set_setting(db, "ai_model", data.ai_model.strip())
    if data.ai_translate_model is not None:
        set_setting(db, "ai_translate_model", data.ai_translate_model.strip())
    if data.ai_explain_model is not None:
        set_setting(db, "ai_explain_model", data.ai_explain_model.strip())
    if data.ai_explain_models is not None:
        set_setting(db, EXPLANATION_MODELS_SETTING, json.dumps([item.model_dump() for item in data.ai_explain_models], ensure_ascii=False))

    db.commit()
    return {"message": "设置已保存"}


@router.get("/quiz")
def get_quiz_settings(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return {
        "quiz_ai_prewarm_enabled": is_quiz_ai_prewarm_enabled(db),
        "wrong_mastery_correct_streak": get_wrong_mastery_correct_streak(db),
    }


@router.put("/quiz")
def update_quiz_settings(
    data: QuizSettingsUpdateRequest,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    streak = data.wrong_mastery_correct_streak
    # 先校验全部输入再做任何写入：set_key 内部会 flush，若先写预热开关再校验阈值，
    # 阈值被拒时预热开关已处于待提交状态，只能依赖事务关闭时的隐式回滚。
    # 手写校验而非 Field(ge=..., le=...)：声明式约束返回 422 且 detail 是数组，
    # 前端读不出可读文案（error-handling.md 有专门约定）。
    if streak is not None and not (
        WRONG_MASTERY_CORRECT_STREAK_MIN <= streak <= WRONG_MASTERY_CORRECT_STREAK_MAX
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                f"错题掌握连对阈值必须是 {WRONG_MASTERY_CORRECT_STREAK_MIN} 到 "
                f"{WRONG_MASTERY_CORRECT_STREAK_MAX} 之间的整数"
            ),
        )

    if data.quiz_ai_prewarm_enabled is not None:
        set_bool_key(db, QUIZ_AI_PREWARM_ENABLED_SETTING, data.quiz_ai_prewarm_enabled)
    if streak is not None:
        set_setting(db, WRONG_MASTERY_CORRECT_STREAK_SETTING, str(streak))
    db.commit()
    return {"message": "设置已保存"}


@router.get("/ai/key")
def get_ai_key(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        return {"ai_api_key": get_effective_ai_api_key(db)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/ai/test")
def test_ai_connection(
    data: AITestRequest,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    import httpx

    try:
        ai_config = get_effective_ai_settings(
            db,
            base_url=data.ai_api_base_url,
            api_key=data.ai_api_key,
            model=data.ai_model,
        )
    except ValueError as exc:
        return {"success": False, "error": str(exc)}

    if not ai_config["api_key"]:
        return {"success": False, "error": "API Key 未配置"}
    if not ai_config["base_url"]:
        return {"success": False, "error": "API Base URL 未配置"}

    # 拼接 URL（复用 ai_service 的逻辑）
    base = ai_config["base_url"].rstrip("/")
    if base.endswith("/chat/completions"):
        api_url = base
    elif base.endswith("/v1"):
        api_url = base + "/chat/completions"
    else:
        api_url = base + "/v1/chat/completions"

    headers = {
        "Authorization": f'Bearer {ai_config["api_key"]}',
        "Content-Type": "application/json",
    }
    payload = build_chat_completion_payload(
        ai_config["model"] or "gpt-4o-mini",
        [
            {"role": "system", "content": "请将以下英文单词翻译为中文，只返回翻译结果。"},
            {"role": "user", "content": "apple"},
        ],
    )

    try:
        resp = httpx.post(api_url, json=payload, headers=headers, timeout=15.0, verify=True)
        if not resp.is_success:
            detail = resp.text[:200] if resp.text else resp.reason_phrase
            return {"success": False, "error": f"API 返回错误 ({resp.status_code}): {detail}"}
        result = resp.json()
        content = result["choices"][0]["message"]["content"]
        return {"success": True, "message": f"连接成功！AI 回复：{content}"}
    except httpx.TimeoutException:
        return {"success": False, "error": "请求超时（15秒），请检查 API 地址是否可达"}
    except httpx.ConnectError:
        return {"success": False, "error": "无法连接到 API 服务器，请检查 URL 是否正确"}
    except Exception as e:
        return {"success": False, "error": f"测试失败：{str(e)}"}
