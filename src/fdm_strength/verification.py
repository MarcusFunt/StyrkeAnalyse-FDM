"""Fail-closed evaluator for the roadmap's four isotropic FEM verification gates."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from math import isfinite, log

ISOTROPIC_FEM_REQUIRED_GATES = (
    "manufactured_solution",
    "uniform_stress_patch",
    "analytical_agreement",
    "calculix_crosscheck",
)
_PINNED_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def observed_l2_convergence_order(mesh_sizes: Sequence[float], errors: Sequence[float]) -> float:
    """Fit the observed L2 error order against actual, strictly refined mesh sizes."""
    if len(mesh_sizes) != len(errors) or len(mesh_sizes) < 2:
        raise ValueError("convergence data requires at least two matching mesh/error samples")
    sizes = tuple(float(value) for value in mesh_sizes)
    error_values = tuple(float(value) for value in errors)
    if any(not isfinite(value) or value <= 0 for value in (*sizes, *error_values)):
        raise ValueError("mesh sizes and errors must be positive finite values")
    if any(left <= right for left, right in zip(sizes, sizes[1:])):
        raise ValueError("mesh sizes must be strictly decreasing")

    log_sizes = tuple(log(value) for value in sizes)
    log_errors = tuple(log(value) for value in error_values)
    mean_size = sum(log_sizes) / len(log_sizes)
    mean_error = sum(log_errors) / len(log_errors)
    variance = sum((value - mean_size) ** 2 for value in log_sizes)
    if variance <= 0:
        raise ValueError("mesh sizes do not span a measurable refinement range")
    covariance = sum(
        (size - mean_size) * (error - mean_error) for size, error in zip(log_sizes, log_errors)
    )
    return covariance / variance


def relative_error(observed: float, reference: float) -> float:
    """Return absolute relative error, rejecting non-finite or zero references."""
    if (
        isinstance(observed, bool)
        or isinstance(reference, bool)
        or not isinstance(observed, (int, float))
        or not isinstance(reference, (int, float))
        or not isfinite(observed)
        or not isfinite(reference)
    ):
        raise ValueError("observed and reference values must be finite numbers")
    if reference == 0:
        raise ValueError("reference must be non-zero")
    return abs(observed - reference) / abs(reference)


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
        "stress_uniformity_relative_range": (
            "max",
            1e-12,
            "stress patch relative range must be at most 1e-12",
        ),
        "displacement_relative_error": (
            "max",
            0.001,
            "patch displacement error must be at most 0.1%",
        ),
        "reaction_force_relative_error": (
            "max",
            0.001,
            "patch reaction-force error must be at most 0.1%",
        ),
    },
    "analytical_agreement": {
        "stress_relative_error": (
            "max",
            0.001,
            "analytical tensile stress error must be at most 0.1%",
        ),
        "strain_relative_error": (
            "max",
            0.001,
            "analytical tensile strain error must be at most 0.1%",
        ),
        "displacement_relative_error": (
            "max",
            0.001,
            "analytical tensile displacement error must be at most 0.1%",
        ),
        "reaction_force_relative_error": (
            "max",
            0.001,
            "analytical tensile reaction-force error must be at most 0.1%",
        ),
    },
    "calculix_crosscheck": {
        "relative_midspan_displacement_error": (
            "max",
            0.005,
            "CalculiX midspan displacement error must be at most 0.5%",
        ),
        "relative_reaction_force_error": (
            "max",
            0.005,
            "CalculiX reaction-force error must be at most 0.5%",
        ),
    },
}


def isotropic_fem_gate_metric_blockers(name: str, metrics: Mapping[str, float]) -> tuple[str, ...]:
    """Return the unmet numerical conditions for one named M4 gate."""
    requirements = _REQUIRED_METRICS.get(name)
    if requirements is None:
        return (f"unknown verification gate: {name}",)
    blockers: list[str] = []
    for metric, (direction, limit, message) in requirements.items():
        observed = metrics.get(metric)
        valid = (
            observed is not None
            and not isinstance(observed, bool)
            and isinstance(observed, (int, float))
            and isfinite(observed)
        )
        passed = valid and (observed >= limit if direction == "min" else observed <= limit)
        if not passed:
            blockers.append(
                message if valid else f"required metric {metric} is missing or non-finite"
            )
    return tuple(blockers)


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
        gate_blockers.extend(isotropic_fem_gate_metric_blockers(name, item.metrics))
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
