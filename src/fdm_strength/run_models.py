"""Versioned, immutable records for formal scientific runs and artifacts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ArtifactReference(FrozenModel):
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    media_type: str = Field(min_length=1, max_length=255)


class StageRecord(FrozenModel):
    stage_id: str = Field(min_length=1, max_length=100)
    operation: str = Field(min_length=1, max_length=100)
    status: Literal["succeeded", "failed"]
    image_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    command: tuple[str, ...] = Field(min_length=1)
    input_artifacts: tuple[ArtifactReference, ...]
    output_artifacts: tuple[ArtifactReference, ...]
    started_at: datetime
    completed_at: datetime
    duration_ms: int = Field(ge=0)
    git_commit: str = Field(min_length=1, max_length=128)
    git_dirty: bool | None
    cpu_count: int = Field(ge=1)
    memory_limit_bytes: int = Field(ge=1)

    @field_validator("started_at", "completed_at")
    @classmethod
    def timestamps_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("stage timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_timing(self) -> StageRecord:
        if self.completed_at < self.started_at:
            raise ValueError("stage completed_at cannot precede started_at")
        if self.status == "succeeded" and not self.output_artifacts:
            raise ValueError("a successful stage requires output artifacts")
        return self


class Run(FrozenModel):
    schema_version: Literal[1] = 1
    id: str = Field(
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    )
    created_at: datetime
    operation: Literal["tensile", "campaign"]
    status: Literal["succeeded", "failed"]
    spec_artifact: ArtifactReference
    input_artifacts: tuple[ArtifactReference, ...]
    output_artifacts: tuple[ArtifactReference, ...]
    result_artifact: ArtifactReference | None
    stages: tuple[StageRecord, ...]
    upstream_run_ids: tuple[str, ...]
    error: str | None = Field(default=None, max_length=4000)

    @field_validator("created_at")
    @classmethod
    def creation_time_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_completion(self) -> Run:
        if self.status == "succeeded" and (self.result_artifact is None or not self.stages):
            raise ValueError("a successful run requires a result artifact and completed stage")
        if self.status == "failed" and not self.error:
            raise ValueError("a failed run must include an error")
        if len(set(self.upstream_run_ids)) != len(self.upstream_run_ids):
            raise ValueError("upstream run IDs must be unique")
        return self
