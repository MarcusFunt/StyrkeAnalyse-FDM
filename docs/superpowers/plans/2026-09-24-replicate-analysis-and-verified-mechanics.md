# Replicate analysis and verified mechanics implementation plan

> **Execution note:** implement one numbered task at a time, test-first, and keep the API/UI build green at each boundary. Do not report scientific gates as passed without executing the pinned solver checks and recording their artifacts.

**Goal:** turn the desktop tensile GUI into a provenance-preserving campaign workflow with specimen-level replicate statistics, conflict-safe retention controls, accessible mobile UX, and gated mechanics validation through the roadmap’s orthotropic and fracture milestones.

**Design:** `docs/superpowers/specs/2026-09-24-replicate-analysis-and-verified-mechanics-design.md`

**Current target branch:** `feat/desktop-echarts-analysis-gui`

## Task 1 — Lock down CSV, mapping, dimensions, and malformed workspace behavior

**Files:** `frontend/src/lib/csv.ts`, `frontend/src/lib/csv.test.ts`, `frontend/src/lib/workspace.ts`, `frontend/src/lib/workspace.test.ts`, `frontend/src/App.tsx`, `frontend/src/styles.css`, Python API tests.

1. Add failing tests for whitespace-padded headers; headers that become empty or duplicate after normalization; row keys matching normalized headers; unmapped/ambiguous force and displacement; same-column mapping; invalid dimensions; malformed rows/settings/results; malformed API workspace payloads.
2. Fix CSV parsing by normalizing header keys and row keys in the same pass, while preserving source-byte provenance separately. Surface duplicate/empty-header errors and parser warnings without silently dropping data.
3. Remove first-column fallbacks. Require two distinct existing mappings and valid positive specimen dimensions; clear/mark a prior result stale whenever its input/settings change.
4. Add one shared set of input limits and validate complete result/workspace shapes on both browser import and API persistence. Invalid workspaces must not mutate current UI state or existing storage.
5. Run frontend regression tests/build and Python API regression tests; confirm the new tests fail against the original behavior before the fixes and pass afterward.

## Task 2 — Add the v2 campaign/specimen model and migration

**Files:** new `src/fdm_strength/study_models.py`, `src/fdm_strength/provenance.py`; `src/fdm_strength/web.py`; new frontend domain types/runtime validators and workspace migration; model/API/browser tests.

1. Add failing Pydantic tests for campaign/configuration/specimen/test-run/print/sensor/input-file metadata, stable IDs, required units, field bounds, duplicate specimen IDs, and missing-vs-measured values.
2. Implement strict v2 models. Hash exact imported bytes with SHA-256 before CSV parsing. Associate each source file and result with a specimen/test run and include analysis/dependency/source provenance.
3. Add a v1-to-v2 migration that preserves rows/settings/results and marks absent metadata as unknown. Reject malformed v1/v2 fields with useful field paths and do not partially load.
4. Extend API and UI serialization without losing v1 study readability. Upgrade only on explicit save; never fabricate sensor, print, or calibration metadata.
5. Test v1 fixture migration round-trip, v2 validation, digest stability, corrupt-file handling, and import/export compatibility.

## Task 3 — Implement specimen and campaign reductions

**Files:** new `src/fdm_strength/replicates.py`, `tests/test_replicates.py`, tensile analysis types/functions, frontend reduction display and tests.

1. Add failing reference tests for engineering stress/strain, interpolation at strain 0.0005 and 0.0025, chord modulus, documented compliance correction, invalid/non-monotonic strain ranges, and unsupported sensor provenance.
2. Implement the per-specimen chord modulus from the design spec. Never label uncorrected crosshead displacement as a validated modulus. Record the algorithm and correction inputs in result provenance.
3. Add campaign aggregations using one specimen value per replicate, arithmetic mean, sample SD (`ddof=1`), CV percent, valid `n`, and explicit undefined/ineligible states.
4. Encode the roadmap’s five-specimen readiness threshold separately from a draft’s ability to display provisional statistics. Never count samples/rows as replicates.
5. Test exact values, sample SD/CV edge cases, missing/invalid specimens, one specimen per ID, and the five-specimen gate.

## Task 4 — Add save-conflict handling, deletion, and retention

**Files:** `src/fdm_strength/web.py`, new storage module if needed, API tests; `frontend/src/App.tsx`, study-list/conflict/trash components, `frontend/src/styles.css`, frontend tests.

1. Add failing API tests for revisions, ETags/`If-Match`, stale-write 409 response, missing preconditions, atomic writes, delete-to-trash, restore, expiry, permanent purge, and corrupt saved records.
2. Implement monotonic revisions and optimistic concurrency. Preserve the client draft on 409; expose reload-current and save-as-copy actions with no silent overwrite.
3. Implement recoverable soft deletion, retention-policy read/update (30-day default), restore, explicit purge, and expiry cleanup. Keep trash state distinct from active state.
4. Add accessible UI for conflict recovery, retention visibility, delete confirmation, restore, and purge. Keep local binding/access assumptions unchanged.
5. Cover concurrent edits and time-controlled expiry in deterministic tests; verify old studies remain readable.

## Task 5 — Add mobile and accessibility end-to-end coverage

**Files:** `frontend/package.json`/lock; Playwright configuration and E2E specs; accessible chart/table markup and UI fixes in `frontend/src/App.tsx`, `frontend/src/ResultsChart.tsx`, `frontend/src/styles.css`; CI workflow.

1. Add failing end-to-end scenarios for import→map→analyze→save→reload; concurrent save conflict/recovery; trash→restore/purge; keyboard-only use; mobile narrow viewport; chart description/table alternative.
2. Add a pinned Playwright/axe test toolchain isolated from Python solver dependencies. Exercise phone and desktop viewports and assert no page-level horizontal overflow or inaccessible primary actions.
3. Fix semantic labels, visible focus, heading/landmark order, dialogs and live errors/status, table scroll labeling, chart text alternatives, and WCAG AA contrast.
4. Require zero serious/critical automated accessibility violations on the core screens and verify keyboard focus entry/return on dialogs.
5. Run browser E2E and accessibility suites locally and in CI; document browser/version and viewport results.

## Task 6 — Reconcile and implement analytical reference models

**Files:** update `docs/roadmap-first-accurate-results.md`; new `src/fdm_strength/analytical.py`, `src/fdm_strength/clt.py`; new reference tests/data.

1. Re-audit roadmap statements against the current branch; clearly date the audit and separate historical state from current GUI implementation. Select and document one enforced unit convention.
2. Research authoritative sources for test/modulus/compliance procedures and mechanics formulas before encoding them; record source, assumptions, and validity limits in code/docs.
3. Add failing hand-computed tests for tensile and three-point-bend references, compliance correction, and laminate `A/B/D` matrices.
4. Implement the smallest analytical reference surface from roadmap M1 and CLT M2, with explicit units, assumptions, bounds, and numerical tolerances.
5. Validate against independently calculated examples and retain golden fixtures with provenance. Do not compare FEM and experiment in this task.

## Task 7 — Build the isotropic FEM verification gate

**Files:** isolated solver container/environment, verification job/CLI and immutable gate record, verification fixtures, API/UI gate status, container/workflow configuration.

1. Inspect and pin the available DOLFINx, Gmsh, PETSc/MPI, and CalculiX toolchain; use separate environments where required by `docs/execution-environments.md`.
2. Add failing verification tests for manufactured-solution convergence order, uniform-stress patch, tensile/bending/CLT reference agreement, and CalculiX C3D10 displacement cross-check.
3. Implement/run each solver check and record exact image digest, dependency versions, mesh family/hash, material, boundary conditions, inputs, outputs, and result hash.
4. Add a gate evaluator that is false by default, tied to an exact solver/model configuration, invalidates on configuration changes, and names each failed/missing criterion.
5. Block all FEM-versus-experiment UI/API paths unless the matching Gate 2 record is complete and passing. Test gate bypass attempts.

## Task 8 — Implement the gated orthotropic model and failure criteria

**Files:** new orthotropic material/model modules; solver adapters and verification fixtures; campaign comparison UI/API and tests; roadmap.

1. Add failing analytical/solver tests for the five independent transversely isotropic constants and local raster-aligned material frame.
2. Implement maximum-stress failure first, then Tsai-Wu with the `F12` assumption explicit and serialized. Preserve material-constant uncertainty and specimen source.
3. Cross-check the model in CalculiX and validate only after Gates 1–2 pass. Tie every prediction to immutable gate and material provenance.
4. Add blinded held-out bend-bar workflow: persist prediction and model digest before access to held-out outcome; then compare with replicate scatter.
5. Keep the comparison disabled when blind provenance, five-specimen campaign readiness, or verification is missing.

## Task 9 — Implement the ordered fracture models

**Files:** new fracture post-processing/model modules; DCB/notched-specimen fixtures and tests; solver environment and gate records; UI/API; roadmap.

1. Add failing reference tests for J-integral/LEFM post-processing and mesh/objectivity convergence on canonical fixtures.
2. Implement J-integral/LEFM first. Add cohesive-zone behavior only with a traceable DCB calibration record and held-out validation.
3. Add phase-field only after orthotropic and cohesive milestones pass their verification/validation gates. Record regularization/length scale and mesh dependence.
4. Gate notched-specimen peak-load and crack-path comparisons on held-out specimen provenance/photos or DIC. Do not implement XFEM under this plan.
5. If required solver capability or experimental data is absent, leave the model explicitly unavailable and report the dependency; never synthesize a passing result.

## Task 10 — Final verification and handoff

1. Run the full Python suite, frontend unit/build, API regression suite, Playwright E2E/accessibility suite, and environment verification appropriate to the available pinned solver images.
2. Run `git diff --check`, inspect the complete diff, confirm workspace-v1 migration, data retention behavior, and comparison-gate enforcement.
3. Update README and roadmap with actual implemented state, commands, required metadata, known unsupported paths, and exact verification artifacts/results.
4. Report completed gates separately from gates that could not run because solver images or measured campaign data were unavailable. Never claim experimental validation from solver verification alone.

## Execution status — 2026-09-24

- **Tasks 1, 3, 4, and 5:** implemented and regression/E2E covered.
- **Task 2:** campaign/specimen/test-run schema, v1 migration, strict validation,
  and raw input-file provenance are implemented. Broader simulation-stage and
  dependency provenance remains for the solver pipeline.
- **Task 6:** unit convention, tensile/bend references, and CLT are implemented
  with analytical tests.
- **Task 7:** the M4 gate evaluator is implemented and fails closed. Solver
  verification itself could not run: there are no pinned DOLFINx/CalculiX
  images or evidence artifacts in this environment, so no FEM comparison is
  authorized.
- **Tasks 8 and 9:** transversely isotropic elasticity, maximum-stress and
  Tsai–Wu references, J-to-K conversion, and a bilinear cohesive envelope are
  implemented. Orthotropic FEM, numerical J-integral, DCB calibration,
  phase-field, and experimental validation remain unavailable until their
  solver and campaign prerequisites pass.
- **Task 10:** Python, frontend, browser, accessibility, and desktop-container
  smoke checks passed. The GUI image now installs the locked Pydantic runtime
  version; CI also starts the built image and checks its health endpoint.
