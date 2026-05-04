"""Pydantic schemas - Settings"""

from pydantic import BaseModel


class AISettingsResponse(BaseModel):
    ai_api_base_url: str
    ai_api_key: str
    ai_api_key_configured: bool
    ai_model: str
    ai_translate_model: str
    ai_explain_model: str


class AISettingsUpdateRequest(BaseModel):
    ai_api_base_url: str | None = None
    ai_api_key: str | None = None
    ai_model: str | None = None
    ai_translate_model: str | None = None
    ai_explain_model: str | None = None


class AITestRequest(BaseModel):
    ai_api_base_url: str | None = None
    ai_api_key: str | None = None
    ai_model: str | None = None


class AITestResponse(BaseModel):
    success: bool
    message: str | None = None
    error: str | None = None
