"""Fail-closed evaluator for the roadmap's four isotropic FEM verification gates."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from math import isfinite

ISOTROPIC_FEM_REQUIRED_GATES = (
    "manufactured_solution",
    "uniform_stress_patch",
    "analytical_agreement",
    "calculix_crosscheck",
)
_PINNED_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class GateEvidence:
    name: str
    passed: bool
    model_digest: str
    artifact_sha256: str
    solver_image_digests: Mapping[str, str]
    metrics: Mapping[str, float] = field(default_factory=dict)
    recorded_at: str = ""


@dataclass(frozen=True)
class GateAssessment:
    comparison_allowed: bool
    missing_gates: tuple[str, ...]
    failed_gates: tuple[str, ...]
    blockers: tuple[str, ...]


_REQUIRED_METRICS: dict[str, dict[str, tuple[str, float, str]]] = {
    "manufactured_solution": {
        "p1_l2_order": ("min", 1.9, "P1 L2 convergence order must be at least 1.9"),
        "p2_l2_order": ("min", 2.9, "P2 L2 convergence order must be at least 2.9"),
    },
    "uniform_stress_patch": {
        "relative_error": ("max", 1e-12, "stress patch relative error must be at most 1e-12"),
    },
    "analytical_agreement": {
        "tensile_relative_error": ("max", 0.001, "tensile stiffness error must be at most 0.1%"),
        "bend_relative_error": ("max", 0.01, "bend stiffness error must be at most 1%"),
        "clt_relative_error": ("max", 0.01, "CLT modulus error must be at most 1%"),
    },
    "calculix_crosscheck": {
        "relative_displacement_error": (
            "max",
            0.005,
            "CalculiX displacement error must be at most 0.5%",
        ),
    },
}


def evaluate_isotropic_fem_gate(
    evidence: Sequence[GateEvidence],
    pinned_solver_images: Mapping[str, str],
    *,
    model_digest: str,
) -> GateAssessment:
    """Allow experiment comparison only for complete, matching, pinned evidence.

    The caller must pass image digests resolved to immutable `sha256:` references.
    The evidence record also binds each result to the exact model configuration
    and a SHA-256 artifact. Empty or malformed configuration fails closed.
    """
    blockers: list[str] = []
    required_images = {"dolfinx", "calculix"}
    for solver in sorted(required_images):
        digest = pinned_solver_images.get(solver)
        if not isinstance(digest, str) or not _PINNED_DIGEST.fullmatch(digest):
            blockers.append(f"{solver} image is not pinned to an immutable sha256 digest")
    if not isinstance(model_digest, str) or not _PINNED_DIGEST.fullmatch(model_digest):
        blockers.append("model configuration must have an immutable sha256 digest")

    by_name: dict[str, GateEvidence] = {}
    duplicate_names: set[str] = set()
    for item in evidence:
        if item.name not in ISOTROPIC_FEM_REQUIRED_GATES:
            blockers.append(f"unknown verification gate: {item.name}")
            continue
        if item.name in by_name:
            duplicate_names.add(item.name)
        by_name[item.name] = item

    missing = tuple(name for name in ISOTROPIC_FEM_REQUIRED_GATES if name not in by_name)
    failed: list[str] = []
    for name in ISOTROPIC_FEM_REQUIRED_GATES:
        item = by_name.get(name)
        if item is None:
            continue
        gate_blockers: list[str] = []
        if name in duplicate_names:
            gate_blockers.append("duplicate evidence record")
        if item.passed is not True:
            gate_blockers.append("recorded gate status is failed")
        if item.model_digest != model_digest:
            gate_blockers.append("evidence belongs to a different model configuration")
        if not isinstance(item.artifact_sha256, str) or not _SHA256.fullmatch(item.artifact_sha256):
            gate_blockers.append("evidence artifact has no valid SHA-256")
        try:
            recorded_at = datetime.fromisoformat(item.recorded_at.replace("Z", "+00:00"))
        except (AttributeError, ValueError):
            recorded_at = None
        if recorded_at is None or recorded_at.utcoffset() is None:
            gate_blockers.append("evidence record must include a timezone-aware timestamp")
        needed_images = {"dolfinx", "calculix"} if name == "calculix_crosscheck" else {"dolfinx"}
        for solver in needed_images:
            expected = pinned_solver_images.get(solver)
            actual = item.solver_image_digests.get(solver)
            if (
                not isinstance(expected, str)
                or not isinstance(actual, str)
                or actual != expected
                or not _PINNED_DIGEST.fullmatch(actual)
            ):
                gate_blockers.append(
                    f"{solver} image digest is missing or does not match the pinned image"
                )
        for metric, (direction, limit, message) in _REQUIRED_METRICS[name].items():
            observed = item.metrics.get(metric)
            valid = (
                observed is not None
                and not isinstance(observed, bool)
                and isinstance(observed, (int, float))
                and isfinite(observed)
            )
            passed = valid and (observed >= limit if direction == "min" else observed <= limit)
            if not passed:
                gate_blockers.append(
                    message if valid else f"required metric {metric} is missing or non-finite"
                )
        if gate_blockers:
            failed.append(name)
            blockers.extend(f"{name}: {message}" for message in gate_blockers)
    if missing:
        blockers.append("all four isotropic FEM verification gates must be recorded")
    return GateAssessment(
        comparison_allowed=not blockers,
        missing_gates=missing,
        failed_gates=tuple(failed),
        blockers=tuple(blockers),
    )


# Backward-compatible aliases for existing notebooks and saved references.
M4_REQUIRED_GATES = ISOTROPIC_FEM_REQUIRED_GATES


def evaluate_m4_gate(
    evidence: Sequence[GateEvidence],
    pinned_solver_images: Mapping[str, str],
    *,
    model_digest: str,
) -> GateAssessment:
    """Deprecated alias for :func:`evaluate_isotropic_fem_gate`."""
    return evaluate_isotropic_fem_gate(
        evidence,
        pinned_solver_images,
        model_digest=model_digest,
    )
