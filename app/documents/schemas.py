"""HTTP schemas for the managed-document API."""

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DocumentFields(StrictRequest):
    title: str = Field(min_length=1, max_length=200, pattern=r"\S")
    body: str = Field(min_length=1, max_length=50_000, pattern=r"\S")
    source_label: str = Field(default="", max_length=200)
    source_url: str | None = Field(default=None, max_length=2_048)
    owner_department: str | None = Field(default=None, max_length=200)
    effective_from: date | None = None

    @field_validator("source_url", "owner_department", mode="before")
    @classmethod
    def blank_optional_text_is_none(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value):
        if value is None:
            return value
        TypeAdapter(AnyHttpUrl).validate_python(value)
        return value

    @field_validator("effective_from", mode="before")
    @classmethod
    def blank_effective_date_is_none(cls, value):
        return None if value == "" else value


class CreateDocumentRequest(DocumentFields):
    pass


class UpdateDocumentRequest(StrictRequest):
    expected_version: int = Field(ge=1, strict=True)
    title: str | None = Field(default=None, min_length=1, max_length=200, pattern=r"\S")
    body: str | None = Field(
        default=None, min_length=1, max_length=50_000, pattern=r"\S"
    )
    source_label: str | None = Field(default=None, max_length=200)
    source_url: str | None = Field(default=None, max_length=2_048)
    owner_department: str | None = Field(default=None, max_length=200)
    effective_from: date | None = None

    @field_validator("source_url", "owner_department", mode="before")
    @classmethod
    def blank_optional_text_is_none(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value):
        if value is None:
            return value
        TypeAdapter(AnyHttpUrl).validate_python(value)
        return value

    @field_validator("effective_from", mode="before")
    @classmethod
    def blank_effective_date_is_none(cls, value):
        return None if value == "" else value

    @field_validator("title", "body")
    @classmethod
    def reject_blank_update_text(cls, value):
        if value is not None and not value.strip():
            raise ValueError("값은 공백일 수 없습니다.")
        return value

    @model_validator(mode="after")
    def reject_null_nonnullable_fields(self):
        for field_name in ("title", "body", "source_label"):
            if (
                field_name in self.model_fields_set
                and getattr(self, field_name) is None
            ):
                raise ValueError(f"{field_name}은 null일 수 없습니다.")
        return self


class PublishDocumentRequest(StrictRequest):
    expected_version: int = Field(ge=1, strict=True)
    revision_id: UUID


class WithdrawDocumentRequest(StrictRequest):
    expected_version: int = Field(ge=1, strict=True)


class RevisionMetadata(BaseModel):
    category: str | None = None
    policy_decision_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    source_version: str | None = None
    review_status: str = "unreviewed"


class DocumentProvenance(BaseModel):
    source_namespace: str
    source_document_id: str
    source_file_sha256: str
    row_sha256: str
    imported_at: str


class RevisionResponse(BaseModel):
    metadata: RevisionMetadata = Field(default_factory=RevisionMetadata)
    id: str
    revision_number: int
    title: str
    body: str
    source_label: str
    source_url: str | None
    owner_department: str | None
    effective_from: date | None
    content_hash: str
    created_at: str


class RevisionSummaryResponse(BaseModel):
    id: str
    revision_number: int
    title: str
    source_label: str
    source_url: str | None
    owner_department: str | None
    effective_from: date | None
    content_hash: str
    created_at: str


class DocumentDetailResponse(BaseModel):
    provenance: DocumentProvenance | None = None
    id: str
    record_version: int
    withdrawn: bool
    created_at: str
    updated_at: str
    status: Literal["draft", "published", "withdrawn"]
    eligibility: Literal["draft", "scheduled", "eligible", "withdrawn"]
    draft: RevisionResponse
    published: RevisionResponse | None


class DocumentSummaryResponse(BaseModel):
    id: str
    record_version: int
    withdrawn: bool
    created_at: str
    updated_at: str
    status: Literal["draft", "published", "withdrawn"]
    eligibility: Literal["draft", "scheduled", "eligible", "withdrawn"]
    draft: RevisionSummaryResponse
    published: RevisionSummaryResponse | None


class DocumentListResponse(BaseModel):
    items: list[DocumentSummaryResponse]
    total: int


class DocumentCapabilitiesResponse(BaseModel):
    management_mode: Literal["local-demo"] = "local-demo"
    answer_integration: Literal["connected"] = "connected"


class MaintenanceRequest(StrictRequest):
    action: Literal["clear", "restore"]
    expected_state: str = Field(pattern=r"^[0-9a-f]{64}$")


class MaintenancePreviewResponse(BaseModel):
    action: Literal["clear", "restore"]
    total_count: int
    restored_count: int
    expected_state: str


class MaintenanceResponse(BaseModel):
    action: Literal["clear", "restore"]
    deleted_count: int
    restored_count: int
    completed_at: str
