"""Pydantic schemas - QuestionBank"""

from datetime import datetime

from pydantic import BaseModel, Field, model_validator

# 平台来源/版本由服务端构造，客户端不得写入；显式拒绝而不是靠 extra=ignore 静默丢弃。
PROVENANCE_FIELDS = (
    "source_platform_bank_id",
    "source_platform_release_id",
    "is_platform_copy",
)


class BankResponse(BaseModel):
    """题库响应格式。"""
    id: int
    name: str
    description: str | None
    source_filename: str | None
    question_count: int
    created_at: str

    model_config = {"from_attributes": True}


class _RejectProvenanceMixin(BaseModel):
    """拒绝客户端提交只读来源/版本字段"""

    @model_validator(mode="before")
    @classmethod
    def _reject_provenance(cls, values):
        if isinstance(values, dict):
            forged = [field for field in PROVENANCE_FIELDS if field in values]
            if forged:
                raise ValueError(f"来源与版本字段为只读，不能修改: {', '.join(forged)}")
        return values


class BankCreateRequest(_RejectProvenanceMixin):
    name: str = Field(..., min_length=1)
    description: str = ""


class BankUpdateRequest(_RejectProvenanceMixin):
    name: str | None = None
    description: str | None = None
