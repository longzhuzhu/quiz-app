"""Pydantic schemas - Auth"""

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    is_admin: bool
    is_active: bool = True
    active_exam_id: int | None = None
    active_exam: dict | None = None
    exam_count: int | None = None
    created_at: str

    model_config = {"from_attributes": True}


class LoginResponse(BaseModel):
    access_token: str
    user: UserResponse


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class ResetPasswordRequest(BaseModel):
    new_password: str


class CreateUserRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=80)
    email: str = Field(..., min_length=1, max_length=120)
    password: str = Field(..., min_length=6)
    is_admin: bool = False


class UpdateUserRequest(BaseModel):
    """管理员对账号的调整；未提供的字段保持不变。"""

    is_admin: bool | None = None
    is_active: bool | None = None


class MessageResponse(BaseModel):
    message: str


class ErrorResponse(BaseModel):
    error: str
