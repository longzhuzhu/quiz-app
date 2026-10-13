"""Pydantic schemas - Settings"""

from pydantic import BaseModel, Field, field_validator


class ExplanationModelSettings(BaseModel):
    model_id: str = Field(min_length=1, max_length=255)
    reasoning_effort: str | None = Field(default="xhigh", min_length=1, max_length=32)

    @field_validator("model_id", "reasoning_effort")
    @classmethod
    def trim_value(cls, value):
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("模型 ID 和推理强度不能是空白字符串")
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("模型 ID 和推理强度不能包含控制字符")
        return value


class AISettingsResponse(BaseModel):
    ai_api_base_url: str
    ai_api_key: str
    ai_api_key_configured: bool
    ai_model: str
    ai_translate_model: str
    ai_explain_model: str
    ai_explain_models: list[ExplanationModelSettings]


class AISettingsUpdateRequest(BaseModel):
    ai_api_base_url: str | None = None
    ai_api_key: str | None = None
    ai_model: str | None = None
    ai_translate_model: str | None = None
    ai_explain_model: str | None = None
    ai_explain_models: list[ExplanationModelSettings] | None = Field(default=None, min_length=1, max_length=5)

    @field_validator("ai_explain_models")
    @classmethod
    def validate_models(cls, value):
        if value is None:
            raise ValueError("解析模型列表不能为空")
        if len({item.model_id for item in value}) != len(value):
            raise ValueError("解析模型 ID 不能重复")
        return value


class QuizSettingsResponse(BaseModel):
    quiz_ai_prewarm_enabled: bool


class QuizSettingsUpdateRequest(BaseModel):
    quiz_ai_prewarm_enabled: bool | None = None


class AITestRequest(BaseModel):
    ai_api_base_url: str | None = None
    ai_api_key: str | None = None
    ai_model: str | None = None


class AITestResponse(BaseModel):
    success: bool
    message: str | None = None
    error: str | None = None
