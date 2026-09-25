"""Allowlisted scientific stage definitions for the runner control plane."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

MiB = 1024 * 1024
GiB = 1024 * MiB


@dataclass(frozen=True)
class StageDefinition:
    """Server-owned execution policy for one scientific stage.

    The browser may select an operation, but it never supplies an image, command,
    resource limit, or stage implementation. Those are owned by this registry so
    Docker-socket access cannot turn into arbitrary container execution.
    """

    stage_id: str
    operations: tuple[str, ...]
    image_reference: str
    command: tuple[str, ...]
    expected_outputs: tuple[str, ...]
    timeout_seconds: int
    cpu_count: int
    memory_limit_bytes: int
    work_size_bytes: int
    max_output_bytes: int
    mpi_ranks: int = 1
    omp_threads: int = 1
    openblas_threads: int = 1

    def __post_init__(self) -> None:
        if not self.stage_id or not self.operations or not self.command or not self.expected_outputs:
            raise ValueError(
                "stage definitions require an id, operations, command, and expected outputs"
            )
        if any(not item or "/" in item for item in self.operations):
            raise ValueError("stage operations must be non-empty simple names")
        if min(
            self.timeout_seconds,
            self.cpu_count,
            self.memory_limit_bytes,
            self.work_size_bytes,
            self.max_output_bytes,
            self.mpi_ranks,
            self.omp_threads,
            self.openblas_threads,
        ) <= 0:
            raise ValueError("stage resource limits must be positive")


_EXPERIMENTAL_REDUCTION = StageDefinition(
    stage_id="experimental-reduction",
    operations=("tensile", "campaign"),
    image_reference="styrkeanalyse-fdm:exp-reduction",
    command=("python", "-m", "fdm_strength.exp_reduction_stage"),
    expected_outputs=("result.json", "provenance.json"),
    timeout_seconds=120,
    cpu_count=1,
    memory_limit_bytes=1 * GiB,
    work_size_bytes=256 * MiB,
    max_output_bytes=128 * MiB,
)

STAGES: Mapping[str, StageDefinition] = MappingProxyType(
    {_EXPERIMENTAL_REDUCTION.stage_id: _EXPERIMENTAL_REDUCTION}
)
OPERATIONS: Mapping[str, StageDefinition] = MappingProxyType(
    {
        operation: stage
        for stage in STAGES.values()
        for operation in stage.operations
    }
)


def stage_for_operation(operation: str) -> StageDefinition:
    try:
        return OPERATIONS[operation]
    except KeyError as error:
        raise ValueError(f"unsupported scientific operation: {operation}") from error


def stage_by_id(stage_id: str) -> StageDefinition:
    try:
        return STAGES[stage_id]
    except KeyError as error:
        raise ValueError(f"unknown scientific stage: {stage_id}") from error
