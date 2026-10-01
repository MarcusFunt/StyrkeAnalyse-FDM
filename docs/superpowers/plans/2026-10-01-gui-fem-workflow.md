# GUI FEM Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an end-to-end GUI workflow for submitting and inspecting immutable isotropic FEM Runs.

**Architecture:** Keep the runner API and server-owned stage registry in control. Add a hashed solver-produced surface preview artifact to the existing formal FEM output contract, and build a focused React page that submits canonical FEM inputs, follows persistent job status, and displays verified Run artifacts and metadata.

**Tech Stack:** Python 3.12, Pydantic, DOLFINx/Gmsh, React 18, TypeScript, Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-01-gui-fem-workflow-design.md`

## Global Constraints

- FEM stage selection is `fdm-l2-isotropic` and all inputs remain sealed in canonical `request.json`.
- Browser requests never provide a solver image, command, or resource limit.
- The preview is a hashed surface element-average view with at most 20,000 triangles; exact `.msh`, `.xdmf`, and `.h5` outputs remain available.
- Run success, M4 method verification, and experimental model validation remain separate states.
- New result metadata is finite JSON and strict about artifact names, media types, hashes, and schema version.

## Review Focus

- P2 geometry DOFs and topological vertices: test boundary extraction uses only corner vertices and excludes shared interior faces.
- Corrupt/unlisted preview artifacts: runner validation test rejects digest, schema, mesh binding, and Run output-list mismatches.
- Failed and long-running jobs: browser test covers error text and visible queued/running states.
- Missing or huge field previews: GUI gives a useful unavailable/too-large state while preserving exact artifact downloads.
- Verification interpretation: UI test asserts `not_assessed` and separately labels experimental validation as not established.

---

### Task 1: Solver-produced field preview artifact

**Files:**
- Create: `src/fdm_strength/fem_preview.py`
- Modify: `src/fdm_strength/isotropic_fem_stage.py`, `src/fdm_strength/stage_registry.py`, `src/fdm_strength/runner_service.py`
- Test: `tests/test_fem_preview.py`, `tests/test_fem_models.py`, `tests/test_run_system.py`

**Interfaces:**
- Produce `build_surface_field_preview(points_mm: Sequence[Sequence[float]], tetrahedra: Sequence[Sequence[int]], von_mises_mpa: Sequence[float], axial_stress_mpa: Sequence[float], axial_displacement_mm: Sequence[float], mesh_sha256: str) -> bytes` with schema version 1, compact boundary points, sampled boundary triangles carrying element-average values, and strict finite/index validation.
- The FEM stage adds `field-preview.json` to expected outputs and the result artifact manifest; runner validation checks schema, mesh digest, finite data, exact declared outputs, and media type.

- [x] Write `test_build_surface_field_preview_emits_all_faces_for_single_tetrahedron` and `test_build_surface_field_preview_excludes_shared_internal_face`; assert triangle count, values, and mesh digest.
- [x] Write `test_build_surface_field_preview_samples_deterministically_over_triangle_limit`; assert the 20,000-triangle cap and repeatable output.
- [x] Run `uv run --frozen pytest tests/test_fem_preview.py -q`; confirm the new helper is missing.
- [x] Implement the pure preview builder and stage/runner output contract.
- [x] Extend mocked stage outputs and strict artifact manifest tests for the preview.
- [x] Run `uv run --frozen pytest tests/test_fem_preview.py tests/test_fem_models.py tests/test_run_system.py -q`.
- [x] Commit as `feat: emit FEM field visualization preview`.

### Task 2: FEM input model and submission form

**Files:**
- Create: `frontend/src/lib/fem.ts`, `frontend/src/lib/fem.test.ts`, `frontend/src/FemPage.tsx`
- Modify: `frontend/src/App.tsx`, `frontend/src/styles.css`

**Interfaces:**
- Export `FemFormValues` with string fields `specimenId`, `lengthMm`, `widthMm`, `thicknessMm`, `materialProfileId`, `youngsModulusMpa`, `poissonsRatio`, `forceN`, `maxCellSizeMm`, plus `elementOrder: 1 | 2` and `optimize: boolean`.
- `buildIsotropicTensileRequest(form: FemFormValues) -> IsotropicTensileRequest` validates finite positive dimensions, force, modulus, valid Poisson ratio, and P1/P2 mesh choice; emits schema version 1, axial-x load/BCs, and millimetre/MPa/N values.
- `createFemSubmission(request: IsotropicTensileRequest) -> Promise<RunSubmissionPayload>` serializes canonical stable JSON, hashes exact UTF-8 bytes using Web Crypto, base64 encodes those bytes, and returns operation `fdm-l2-isotropic` with input name `request.json`, FEM request media type, empty parameters, and no upstream Runs.
- `FemPage` accepts submit/status/result callbacks and renders the explicit stage inputs plus Run status.

- [x] Write `test_build_isotropic_tensile_request_keeps_units_and_mesh_order_explicit`, `test_create_fem_submission_hashes_exact_canonical_bytes`, and `test_build_isotropic_tensile_request_rejects_invalid_dimensions_and_material`.
- [x] Run `npm test --prefix frontend -- src/lib/fem.test.ts`; confirm the helper is missing.
- [x] Implement validated request/submission helpers and the FEM form page.
- [x] Add the FEM navigation route and server-poll status callback (`queued`, `running`, terminal state) without changing tensile polling behavior.
- [x] Run `npm test --prefix frontend -- src/lib/fem.test.ts` and `npm run build --prefix frontend`.
- [x] Commit as `feat: add isotropic FEM submission page`.

### Task 3: Immutable Run results, viewer, and evidence panel

**Files:**
- Create: `frontend/src/FemRunDetail.tsx`, `frontend/src/FemFieldViewer.tsx`, `frontend/src/lib/femRun.ts`, `frontend/src/lib/femRun.test.ts`
- Modify: `frontend/src/FemPage.tsx`, `frontend/src/App.tsx`, `frontend/src/styles.css`

**Interfaces:**
- `loadFemRun(runId: string, fetcher: typeof fetch = fetch) -> Promise<FemRunDetailData>` fetches the Run and result artifact, verifies the envelope ID and that preview digest appears among immutable Run outputs, then fetches/parses the preview with finite numeric and a 16 MiB size guard.
- `FemFieldViewer` renders boundary triangle averages for von Mises stress, axial stress, or axial displacement, with rotate controls and mesh-edge toggle; it labels the view as a surface approximation.
- Run detail presents scalar results, explicit `not_assessed` status, separate validation state, material/BC/mesh identities, runtime/image/source/dependency provenance, and SHA-linked artifact downloads.

- [x] Write `test_parse_fem_run_binds_preview_to_declared_output_and_mesh`, `test_parse_fem_run_rejects_missing_or_malformed_preview`, `test_parse_fem_run_rejects_preview_over_size_limit`, and `test_fem_run_detail_labels_run_gate_and_validation_separately`.
- [x] Run `npm test --prefix frontend -- src/lib/femRun.test.ts`; confirm the loader is missing.
- [x] Implement fail-closed loading, SVG mesh field rendering, scalar/provenance cards, and artifact downloads.
- [x] Run the targeted Vitest files and `npm run build --prefix frontend`.
- [x] Commit as `feat: inspect FEM fields and provenance in GUI`.

### Task 4: Browser integration and end-to-end verification

**Files:**
- Modify: `frontend/e2e/gui.spec.ts`, `README.md` or `docs/roadmap-first-accurate-results.md`

**Interfaces:**
- The browser workflow exercises actual `/api/runs`, `/api/jobs`, `/api/artifacts` endpoints and the existing pinned stage image; no mocked solver result.

- [ ] Add a Playwright scenario submitting a P1 tensile solve, observing queued/running/succeeded state, and checking scalar, visualization, provenance, verification labels, and all solver-artifact links.
- [ ] Add a browser scenario for a failed FEM job, verifying the runner error is shown.
- [ ] Run frontend browser checks and the full repository Verify workflow, including a clean pinned-image FEM solve.
- [ ] Commit as `test: cover GUI FEM submission and inspection`.
