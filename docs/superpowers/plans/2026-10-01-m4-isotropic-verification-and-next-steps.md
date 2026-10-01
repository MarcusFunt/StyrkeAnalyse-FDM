# M4 Isotropic FEM Verification and Next Steps

For agentic workers: follow this plan in order. Treat the M4 evidence as solver output, not as hand-authored fixture data. Keep each verification case small and independently reviewable, and run the repository's full `Verify` workflow before proposing the verification PR for merge.

## Goal

Turn the merged `fdm-l2-isotropic` tensile solver from a reproducible smoke-tested stage into a scientifically verified stage. Preserve the asynchronous runner, immutable Runs, content-addressed artifacts, server-owned stage registry, fail-closed restart behavior, immutable campaign inputs, and complete solver provenance already on `main`.

The M4 outcome is a hashed evidence bundle containing actual solver results for manufactured-solution convergence, a uniform-stress patch, analytical tensile agreement, and an independent CalculiX cross-check. The fail-closed evaluator must accept that bundle for the exact solver/model configuration, and experiment-comparison eligibility must remain false when evidence is missing, stale, malformed, or failing.

## Architecture

Use the formal runner and immutable stage contracts for DOLFINx and CalculiX execution. Extract only the shared elasticity assembly needed by the production stage and verification cases; do not create a second untracked solver path. Make the verification command emit a versioned report with numerical metrics, exact image identities, model digest, timestamps, and SHA-256 references to its evidence artifacts. Pass those records through `evaluate_isotropic_fem_gate`.

Keep verification status separate from a particular solve's result. A normal solve remains `not_assessed`; only a matching accepted verification assessment makes its model eligible for later comparison. Do not add FEM-versus-experiment conclusions to the GUI in this milestone.

## Tech Stack

- Python 3.12, `uv.lock`, pytest, Pydantic stage contracts.
- Digest-pinned DOLFINx/PETSc/MPI container and an independently built, version-identified CalculiX container.
- Gmsh mesh inputs and DOLFINx weak-form assembly for manufactured, patch, and tensile cases.
- CalculiX input deck using the same mesh, constants, and kinematic constraints as the matching DOLFINx case.
- GitHub Actions `Verify` workflow for container builds, numerical gate execution, report validation, and regression coverage.

## Spec

### Current repository state

- `main`, `origin/main`, and `HEAD` were all at `e742543` (PR #9 merge) when this plan was written.
- PR #7's asynchronous persistent runner/provenance architecture and PR #8's pre-rig plan are merged. PR #9 adds `fem_models.py` and `isotropic_fem_stage.py`, registers the formal operation, emits mesh/field/result/provenance artifacts, and exercises a real solve plus replay in container CI.
- `result.json` deliberately says `verification_status: not_assessed`. There are no solver-generated M4 evidence records yet. The existing evaluator in `src/fdm_strength/verification.py` fails closed.
- The frontend currently analyzes experimental tensile curves and campaign readiness. It does not submit FEM jobs or visualize mesh/field results.
- The evaluator currently requires bending and CLT error metrics under `analytical_agreement`; the immediate M4 requirement is the rectangular tensile solution (`σ = F/A`, `ε = σ/E`, `ΔL = FL/(AE)`). Resolve this contract mismatch before recording M4 as green. Recommended scope: make M4's analytical gate tensile-specific, then verify bending and CLT in their own later cases. If the project instead keeps the wider gate, it must produce those additional solver-backed records before claiming M4 complete.

### Work sequence: verification PR

### Task 1: Align the fail-closed evidence contract

In `src/fdm_strength/verification.py` and `tests/test_mechanics_models.py`, define the M4 metric names, units, tolerances, canonical model digest inputs, solver image identities, artifact hashing, and report schema. Write tests first for tensile-only analytical metrics, missing/duplicate/stale-model/wrong-image/non-finite/out-of-tolerance evidence. Keep the evaluator fail-closed. Record why the M4 analytical scope is tensile-only; move bending and CLT metrics to their later verification cases.

**Check:** `uv run pytest -q tests/test_mechanics_models.py` fails on the new contract cases before implementation and passes after the change.

### Task 2: Generate DOLFINx convergence, patch, and tensile evidence

Add a solver verification entry point inside the pinned isotropic FEM image. Reuse the production elasticity form. For a manufactured smooth displacement field, run P1 and P2 on several refined meshes, calculate L2 displacement errors and observed orders, and emit mesh sizes, solver settings, and mesh hashes. Run a rectangular tensile case and record stress uniformity, displacement, and integrated reaction; compare stress, strain, and extension with `σ = F/A`, `ε = σ/E`, and `ΔL = FL/(AE)`. Check force balance and boundary conditions. Keep the current patch tolerance (`1e-12`) unless solver residuals demonstrate a numerical reason to adjust it.

**Check:** add container-backed numerical assertions for the convergence orders (P1 ≥ 1.9, P2 ≥ 2.9), patch stress, and analytical tensile quantities; demonstrate a failing assertion before implementation.

### Task 3: Cross-check a matching case in CalculiX

Use the same generated mesh, material, specimen, and effective boundary conditions. Emit and run the CalculiX input deck; compare average interior midspan axial displacement and integrated reaction force numerically. Midspan displacement avoids comparing a prescribed loaded-face DOF, which is identical by construction. Bind the report to both solver image digests and the material/mesh/boundary-condition hashes. Add a dedicated pinned CalculiX image/build path if the current environment cannot provide a stable image identity.

**Check:** a container-backed cross-solver assertion compares midspan displacement and reaction within the documented tolerance and fails when a mesh or BC hash is changed.

### Task 4: Emit and retain the complete assessment report

Add `scripts/verify_isotropic_fem.py` and a versioned JSON report. It must execute the four solver cases, serialize `GateEvidence`, calculate artifact hashes, capture exact image identities, and call `evaluate_isotropic_fem_gate`. Preserve meshes, solver outputs, summaries, and report as CI artifacts. Add a regression showing an altered model digest or missing gate returns `comparison_allowed == false`.

**Check:** the report validator accepts the complete real evidence and rejects incomplete or mismatched evidence.

### Task 5: Run the complete Verify workflow

Update `.github/workflows/verify.yml` to run the verification command against the built images alongside the existing checks. Keep unit-level gate wiring in regular CI and retain the numerical evidence bundle. Run the full workflow and fix any failures before proposing the M4 verification PR.

**Check:** `uv run pytest -q`, frontend tests/build, both required Docker builds, container workflow smoke, and the full M4 solver verification complete successfully in the `Verify` workflow.

### Follow-on sequence after M4

1. Add three-point bending with an explicitly tested quadratic or higher-order element. Compare with beam theory including the applicable shear correction, test mesh sensitivity and element-order effects, and retain it as the held-out validation geometry. Do not use bending FEM for experiment comparison until its own verification checks pass.
2. Freeze the rig `manifest.json`, `raw.csv`, and immutable calibration-record contract before firmware output is finalized. Exercise it with generated files through normal import and reduction. This schema task is independent of M4 and can proceed alongside it if the firmware format is nearing freeze.
3. Add the FEM GUI once the solver interface and verification assessment are stable: specimen/material/mesh/BC setup, asynchronous job states, scalar outputs, mesh and displacement/stress field viewing, legends and units, artifacts/provenance, and a visible verification state. Keep replicate readiness, solver verification, and model validation visibly distinct.
4. Implement orthotropic FEM with explicit `E1/E2/E3`, Poisson ratios, shear moduli, material axes, maximum-stress and Tsai-Wu indices, and configured `F12`; cross-check simple cases and the CalculiX engineering-constants model.
5. Generate synthetic campaigns with scatter, noise, invalid runs, and multiple print orientations. Verify recovery of known parameters, freeze an immutable material profile, and rehearse the blind held-out bending prediction/unblinding workflow end-to-end.
6. Extend `ToolpathModel` through specimen registration and mesh-element orientation assignment only after homogeneous orthotropic FEM is sound. Compare isotropic CAD, homogeneous orthotropic, and locally G-code-oriented models with other inputs fixed.
7. Keep fracture work bounded to schemas, notched geometries, analytical LEFM/J references, and verification fixtures. Defer fracture calibration and large parameter studies until physical measurements exist.

## Global Constraints

- Do not expose FEM-versus-experiment conclusions before the relevant solver verification assessment passes.
- Do not replace real solver evidence with unit-test fixtures or visual screenshots.
- Bind evidence to immutable solver image IDs, exact code/model configuration, material, mesh, boundary conditions, and artifact hashes.
- Keep MPI, OpenMP, BLAS, and CPU resource settings explicit and checked against the stage contract.
- Preserve immutable Runs and campaign inputs; persist results and evidence as content-addressed artifacts.
- Avoid runner architecture expansion unless an actual verification case demonstrates a missing requirement.
- Defer Kubernetes, distributed scheduling, generic plugin systems, large RVE/voxel workflows, speculative ML, and fracture calibration.

## Review Focus

- Does each evidence record originate from a reproducible solver execution and bind to the exact model, mesh, material, boundary conditions, solver version, and image digest?
- Are convergence orders calculated from multiple mesh resolutions with a documented error norm?
- Does the patch case check stress, displacement, and force balance without applying accidental constraints that suppress lateral expansion?
- Are CalculiX and DOLFINx solving mechanically equivalent problems on the same mesh, and are differences compared numerically?
- Does the evaluator stay fail-closed for absent, stale, mismatched, malformed, or non-finite evidence?
- Can CI show the evidence and assessment that made the gate green, without turning a one-off smoke solve into a scientific claim?
- Are bending/CLT requirements either met with real evidence or explicitly moved out of the immediate tensile M4 gate?
