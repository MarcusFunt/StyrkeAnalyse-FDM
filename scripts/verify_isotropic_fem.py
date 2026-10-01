#!/usr/bin/env python3
"""Run solver-backed M4 verification and retain a content-hashed report bundle."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from fdm_strength.isotropic_fem_report import (
    assess_m4_report,
    build_m4_report,
    write_m4_report,
)


def _docker(*arguments: str, capture: bool = False) -> str:
    completed = subprocess.run(
        ["docker", *arguments],
        check=False,
        capture_output=capture,
        text=True,
        timeout=900,
    )
    if completed.returncode != 0:
        output = (completed.stderr or "") + (completed.stdout or "")
        raise RuntimeError(f"docker command failed ({completed.returncode}): {output.strip()}")
    return completed.stdout.strip() if capture else ""


def _image_id(image: str) -> str:
    digest = _docker("image", "inspect", "--format", "{{.Id}}", image, capture=True)
    if not digest.startswith("sha256:"):
        raise RuntimeError(f"Docker did not return an immutable image ID for {image}")
    return digest


def _image_labels(image: str) -> dict[str, str]:
    raw = _docker("image", "inspect", "--format", "{{json .Config.Labels}}", image, capture=True)
    labels = json.loads(raw) if raw else {}
    if not isinstance(labels, dict):
        raise RuntimeError(f"Docker image labels are malformed for {image}")
    return {str(key): str(value) for key, value in labels.items()}


def _git_revision_and_clean() -> str:
    repository_root = Path(__file__).resolve().parents[1]
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository_root,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.strip()
    if re.fullmatch(r"[0-9a-f]{40}", revision) is None:
        raise RuntimeError("git did not return a full source revision")
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=repository_root,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.splitlines()
    # Codex stores opaque task attachments here; the Docker build context excludes
    # them. Ignore only that exact top-level path without opening its contents.
    changes = [
        line
        for line in status
        if not line[3:].replace("\\", "/").startswith(".codex-remote-attachments/")
    ]
    if changes:
        raise RuntimeError("M4 report generation requires a clean source checkout")
    return revision


def _verify_image_labels(labels: dict[str, str], git_commit: str, solver: str) -> None:
    expected = {
        "org.opencontainers.image.revision": git_commit,
        "fdm.git.commit": git_commit,
        "fdm.git.dirty": "false",
    }
    for key, value in expected.items():
        if labels.get(key) != value:
            raise RuntimeError(
                f"{solver} image label {key} does not match clean revision {git_commit}"
            )


def _volume_path(path: Path) -> str:
    # Docker Desktop accepts forward slashes for Windows host paths.
    return path.resolve().as_posix()


def _run_solver(image: str, output_dir: Path, *command: str, workdir: str = "/work") -> None:
    _docker(
        "run",
        "--rm",
        "--user",
        "0:0",
        "--volume",
        f"{_volume_path(output_dir)}:/verification",
        "--workdir",
        workdir,
        "--env",
        "OMP_NUM_THREADS=1",
        "--env",
        "OPENBLAS_NUM_THREADS=1",
        "--env",
        "MKL_NUM_THREADS=1",
        "--env",
        "NUMEXPR_NUM_THREADS=1",
        image,
        *command,
    )


def run_verification(
    output_dir: Path,
    *,
    dolfinx_image: str,
    calculix_image: str,
    git_commit: str,
) -> dict[str, object]:
    actual_commit = _git_revision_and_clean()
    if git_commit != actual_commit:
        raise ValueError(
            f"requested git commit {git_commit!r} does not match checkout {actual_commit}"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    if any(output_dir.iterdir()):
        raise ValueError("M4 evidence output directory must be empty to prevent stale artifacts")

    dolfinx_digest = _image_id(dolfinx_image)
    calculix_digest = _image_id(calculix_image)
    dolfinx_labels = _image_labels(dolfinx_image)
    calculix_labels = _image_labels(calculix_image)
    _verify_image_labels(dolfinx_labels, actual_commit, "DOLFINx")
    _verify_image_labels(calculix_labels, actual_commit, "CalculiX")
    _run_solver(
        dolfinx_digest,
        output_dir,
        "python",
        "-m",
        "fdm_strength.isotropic_fem_verification",
        "--output-dir",
        "/verification",
    )
    _run_solver(calculix_digest, output_dir, "ccx", "-i", "tensile", workdir="/verification")
    calculix_version = _docker(
        "run",
        "--rm",
        "--entrypoint",
        "/bin/cat",
        calculix_digest,
        "/opt/calculix-version",
        capture=True,
    )
    report = build_m4_report(
        output_dir,
        dolfinx_image_digest=dolfinx_digest,
        calculix_image_digest=calculix_digest,
        dolfinx_image_labels=dolfinx_labels,
        calculix_image_labels=calculix_labels,
        calculix_version=calculix_version,
        git_commit=git_commit,
    )
    report_path = write_m4_report(report, output_dir)
    assessment = assess_m4_report(report, output_dir)
    print(json.dumps(report["assessment"], indent=2, sort_keys=True))
    print(f"M4 report: {report_path}")
    if not assessment.comparison_allowed:
        print("M4 verification failed closed; see report blockers above.", file=sys.stderr)
        return {"passed": False, "report": report}
    return {"passed": True, "report": report}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dolfinx-image", required=True)
    parser.add_argument("--calculix-image", required=True)
    parser.add_argument("--git-commit", default=os.environ.get("GITHUB_SHA"))
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        git_commit = args.git_commit or _git_revision_and_clean()
        result = run_verification(
            args.output_dir,
            dolfinx_image=args.dolfinx_image,
            calculix_image=args.calculix_image,
            git_commit=git_commit,
        )
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"M4 verification could not produce an assessment: {exc}", file=sys.stderr)
        return 2
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
