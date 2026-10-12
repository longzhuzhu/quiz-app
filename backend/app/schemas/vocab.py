"""Pydantic schemas - Vocabulary"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator, model_validator


class VocabItemResponse(BaseModel):
    id: int
    term: str
    definition: str | None = None
    term_zh: str | None = None
    definition_zh: str | None = None
    is_system: bool
    is_mastered: bool
    can_delete: bool
    can_mark_mastered: bool = True
    created_at: str


class VocabAddRequest(BaseModel):
    term: str
    definition: str = ""
    term_zh: str | None = None
    definition_zh: str | None = None
    auto_translate: bool = False


class VocabProgressUpdateRequest(BaseModel):
    is_mastered: bool


class FrequentProgressUpdateRequest(BaseModel):
    bank_id: int
    term: str
    is_mastered: bool


class StudyVocabularyRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    vocabulary_id: StrictInt = Field(gt=0)


class StudyFrequentRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    term: str = Field(min_length=1, max_length=200, strict=True)

    @model_validator(mode="after")
    def nonblank_identity(self):
        if not self.term.strip() or self.term != self.term.strip():
            raise ValueError("term 必须为非空且无首尾空白的词条身份")
        return self


class StudyItemsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Literal["personal", "exam_personal", "frequent"]
    bank_id: StrictInt | None = Field(default=None, gt=0)
    refs: list[StudyVocabularyRef | StudyFrequentRef] = Field(min_length=1, max_length=500)
    include_content: StrictBool = True

    @model_validator(mode="after")
    def validate_batch(self):
        frequent = self.scope == "frequent"
        if not frequent and "bank_id" in self.model_fields_set:
            raise ValueError("普通词禁止携带 bank_id")
        if frequent != (self.bank_id is not None):
            raise ValueError("仅高频词必须指定 bank_id")
        expected = StudyFrequentRef if frequent else StudyVocabularyRef
        if any(not isinstance(ref, expected) for ref in self.refs):
            raise ValueError("引用与来源不匹配")
        identities = [ref.term if frequent else ref.vocabulary_id for ref in self.refs]
        if len(set(identities)) != len(identities):
            raise ValueError("引用不得重复")
        if self.include_content and len(self.refs) > 100:
            raise ValueError("内容批读最多 100 词")
        return self


class StudyContextResponse(BaseModel):
    scope: Literal["personal", "exam_personal", "frequent"]
    exam_id: int | None
    bank_id: int | None


class StudyRefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Literal["personal", "exam_personal", "frequent"]
    bank_id: StrictInt | None = Field(default=None, gt=0)
    ref: StudyVocabularyRef | StudyFrequentRef

    @model_validator(mode="after")
    def validate_source(self):
        # 与批读共用来源/身份约束，尤其不能将跨项目词条伪装成个人词。
        source = {"bank_id": self.bank_id} if "bank_id" in self.model_fields_set else {}
        StudyItemsRequest(scope=self.scope, refs=[self.ref], **source)
        return self


class VocabRefreshContent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    term_zh: str = Field(strict=True, min_length=1, max_length=200)
    definition: str = Field(strict=True, min_length=1, max_length=10000)
    definition_zh: str = Field(strict=True, min_length=1, max_length=10000)

    @field_validator("term_zh", "definition", "definition_zh", mode="before")
    @classmethod
    def trim_text(cls, value):
        return value.strip() if isinstance(value, str) else value


class StudyDeckResponse(BaseModel):
    schema_version: Literal[1]
    context: StudyContextResponse
    mastery: Literal["all", "unmastered", "mastered"]
    refs: list[StudyVocabularyRef | StudyFrequentRef]
    total: int = Field(ge=0)
    top_limit: Literal[5000] | None


class StudyContentResponse(BaseModel):
    term: str
    term_zh: str | None
    definition: str | None
    definition_zh: str | None
    frequency: int | None


class StudyRefreshResponse(BaseModel):
    ref: StudyVocabularyRef | StudyFrequentRef
    content: StudyContentResponse


class StudyAvailableResult(BaseModel):
    ref: StudyVocabularyRef | StudyFrequentRef
    available: Literal[True]
    is_mastered: bool
    can_mark_mastered: bool
    can_delete: bool
    content: StudyContentResponse | None


class StudyUnavailableResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ref: StudyVocabularyRef | StudyFrequentRef
    available: Literal[False]


class StudyItemsResponse(BaseModel):
    results: list[StudyAvailableResult | StudyUnavailableResult]


class VocabStatsResponse(BaseModel):
    personal: int
    exam_personal: int
    all: int


class BatchTranslateResponse(BaseModel):
    message: str
    translated: int
    remaining: int


class FrequentListResponse(BaseModel):
    bank: dict
    summary: dict
    pagination: dict
    items: list[dict]


class ImportIAPPResponse(BaseModel):
    message: str
    added: int
    skipped: int
    total_fetched: int
