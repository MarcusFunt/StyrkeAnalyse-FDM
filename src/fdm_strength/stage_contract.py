"""File-based contract shared by the runner and isolated stage containers."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class StageInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    name: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    media_type: str = Field(min_length=1, max_length=255)

    @field_validator("name")
    @classmethod
    def require_safe_filename(cls, value: str) -> str:
        if value in {".", ".."} or not _SAFE_NAME.fullmatch(value):
            raise ValueError("stage input must use a safe filename")
        return value


class StageContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[1]
    run_id: str
    stage_id: str
    operation: Literal["tensile", "campaign"]
    inputs: tuple[StageInput, ...]
    parameters: dict[str, Any]
    expected_outputs: tuple[str, ...] = Field(min_length=1)

    @field_validator("run_id")
    @classmethod
    def require_canonical_uuid(cls, value: str) -> str:
        try:
            if str(uuid.UUID(value)) != value:
                raise ValueError
        except (ValueError, AttributeError, TypeError) as error:
            raise ValueError("run_id must be a canonical UUID") from error
        return value

    @field_validator("stage_id")
    @classmethod
    def validate_stage_id(cls, value: str) -> str:
        if not _SAFE_NAME.fullmatch(value):
            raise ValueError("stage_id must be a safe name")
        return value

    @field_validator("expected_outputs")
    @classmethod
    def validate_output_names(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            if value in {".", ".."} or not _SAFE_NAME.fullmatch(value):
                raise ValueError("expected output must use a safe filename")
        if len(set(values)) != len(values):
            raise ValueError("expected output filenames must be unique")
        return values

    @model_validator(mode="after")
    def validate_input_names(self) -> StageContract:
        names = [artifact.name for artifact in self.inputs]
        if len(set(names)) != len(names):
            raise ValueError("stage input filenames must be unique")
        return self


def load_stage_contract(work_root: str | Path = "/work") -> StageContract:
    root = Path(work_root).resolve(strict=True)
    contract_path = root / "run.json"
    if contract_path.is_symlink() or not contract_path.is_file():
        raise ValueError("/work/run.json must be a regular file")
    try:
        contract = StageContract.model_validate_json(contract_path.read_bytes())
    except (OSError, ValidationError, ValueError) as error:
        raise ValueError(f"invalid /work/run.json stage contract: {error}") from error

    input_root = root / "in"
    if input_root.is_symlink() or not input_root.is_dir():
        raise ValueError("/work/in must be a directory")
    resolved_input_root = input_root.resolve(strict=True)
    for artifact in contract.inputs:
        input_path = input_root / artifact.name
        if input_path.is_symlink() or not input_path.is_file():
            raise ValueError(f"stage input {artifact.name} must be a regular file")
        if input_path.resolve(strict=True).parent != resolved_input_root:
            raise ValueError(f"stage input {artifact.name} escapes /work/in")
        content = input_path.read_bytes()
        if len(content) != artifact.size_bytes:
            raise ValueError(f"stage input {artifact.name} size mismatch")
        if hashlib.sha256(content).hexdigest() != artifact.sha256:
            raise ValueError(f"stage input {artifact.name} digest mismatch")

    output_root = root / "out"
    if output_root.is_symlink() or not output_root.is_dir():
        raise ValueError("/work/out must be a directory")
    if any(output_root.iterdir()):
        raise ValueError("/work/out must be empty before the stage runs")
    return contract


def read_stage_outputs(
    work_root: str | Path,
    contract: StageContract,
) -> dict[str, bytes]:
    output_root = Path(work_root).resolve(strict=True) / "out"
    if output_root.is_symlink() or not output_root.is_dir():
        raise ValueError("/work/out must be a directory")
    actual_paths = list(output_root.iterdir())
    actual_names = {path.name for path in actual_paths}
    expected_names = set(contract.expected_outputs)
    if actual_names != expected_names:
        raise ValueError(
            "stage outputs do not match the contract: "
            f"expected {sorted(expected_names)}, received {sorted(actual_names)}"
        )
    outputs: dict[str, bytes] = {}
    for path in actual_paths:
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"stage output {path.name} must be a regular file")
        outputs[path.name] = path.read_bytes()
    return outputs


def canonical_contract_bytes(contract: StageContract) -> bytes:
    return (
        json.dumps(
            contract.model_dump(mode="json"),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
