"""Strict, versioned execution provenance emitted by isolated stage images."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ProvenanceArtifact(_FrozenModel):
    name: str = Field(min_length=1, max_length=128)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    media_type: str = Field(min_length=1, max_length=255)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not _SAFE_NAME.fullmatch(value):
            raise ValueError("provenance artifact name must be a safe filename")
        return value


class StageProvenance(_FrozenModel):
    """Complete execution manifest for one immutable stage invocation."""

    schema_version: Literal[2] = 2
    run_id: str = Field(min_length=36, max_length=36)
    stage_id: str = Field(min_length=1, max_length=100)
    operation: str = Field(min_length=1, max_length=100)
    image_reference: str = Field(min_length=1, max_length=512)
    image_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    base_image_reference: str | None = Field(default=None, max_length=512)
    dependency_lock_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    contract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    entrypoint: tuple[str, ...] = Field(min_length=1, max_length=32)
    inputs: tuple[ProvenanceArtifact, ...]
    outputs: tuple[ProvenanceArtifact, ...] = Field(min_length=1)
    git_commit: str = Field(min_length=1, max_length=128)
    git_dirty: bool | None
    solver_name: str | None = Field(default=None, min_length=1, max_length=100)
    solver_version: str | None = Field(default=None, min_length=1, max_length=100)
    mesh_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    mesh_parameters: dict[str, Any] | None = None
    material_profile_id: str | None = Field(default=None, min_length=1, max_length=128)
    material_profile_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    boundary_condition_set_id: str | None = Field(default=None, min_length=1, max_length=128)
    mpi_ranks: int = Field(ge=1, le=1024)
    omp_threads: int = Field(ge=1, le=1024)
    cpu_count: int = Field(ge=1, le=1024)
    memory_limit_bytes: int = Field(ge=1)
    started_at: datetime
    completed_at: datetime
    runtime_versions: dict[str, str]

    @field_validator("stage_id")
    @classmethod
    def validate_stage_id(cls, value: str) -> str:
        if not _SAFE_NAME.fullmatch(value):
            raise ValueError("stage_id must be a safe name")
        return value

    @field_validator("run_id")
    @classmethod
    def validate_run_id(cls, value: str) -> str:
        try:
            if str(uuid.UUID(value)) != value:
                raise ValueError
        except (ValueError, AttributeError, TypeError) as error:
            raise ValueError("run_id must be a canonical UUID") from error
        return value

    @field_validator("operation")
    @classmethod
    def validate_operation(cls, value: str) -> str:
        if not _SAFE_NAME.fullmatch(value):
            raise ValueError("operation must be a safe name")
        return value

    @field_validator("image_reference", "base_image_reference")
    @classmethod
    def validate_image_reference(cls, value: str | None) -> str | None:
        if value is not None and (
            not value.strip() or any(char.isspace() for char in value)
        ):
            raise ValueError("image references must be non-empty and contain no whitespace")
        return value

    @field_validator("entrypoint")
    @classmethod
    def validate_entrypoint(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not part or "\x00" in part for part in value):
            raise ValueError("entrypoint arguments must be non-empty and contain no NUL")
        return value

    @field_validator("started_at", "completed_at")
    @classmethod
    def timestamps_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("stage timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_invocation(self) -> StageProvenance:
        if self.completed_at < self.started_at:
            raise ValueError("stage completed_at cannot precede started_at")
        if (self.solver_name is None) != (self.solver_version is None):
            raise ValueError("solver name and version must be supplied together")
        if (self.mesh_sha256 is None) != (self.mesh_parameters is None):
            raise ValueError("mesh hash and mesh parameters must be supplied together")
        if (self.material_profile_id is None) != (self.material_profile_sha256 is None):
            raise ValueError("material profile ID and hash must be supplied together")
        if self.mpi_ranks * self.omp_threads > self.cpu_count:
            raise ValueError("MPI ranks multiplied by OMP threads cannot exceed allocated CPUs")
        if len({artifact.name for artifact in self.inputs}) != len(self.inputs):
            raise ValueError("stage input artifact names must be unique")
        if len({artifact.name for artifact in self.outputs}) != len(self.outputs):
            raise ValueError("stage output artifact names must be unique")
        if any(not key or not value for key, value in self.runtime_versions.items()):
            raise ValueError("runtime version entries must have non-empty names and values")
        return self
