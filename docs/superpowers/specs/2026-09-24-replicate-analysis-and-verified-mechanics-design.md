# Replicate analysis and verified mechanics design

**Status:** Proposed for review

**Date:** 2026-09-24

**Repository:** `feat/desktop-echarts-analysis-gui`

## Purpose and project goal

StyrkeAnalyse-FDM is intended to determine whether FDM manufacturing information improves strength and fracture predictions. It should preserve traceable experimental evidence, calculate transparent baseline and material-model results, and only compare a numerical model with experiments after the model has passed independent verification. The current branch provides a desktop-hosted tensile-baseline GUI and local study storage; it does not yet provide campaign/replicate data, mechanics solvers, or a verification-gated comparison workflow.

This work closes the gap between a single imported tensile curve and a reproducible experimental campaign, hardens desktop study persistence, and establishes the scientific gates needed before extending to orthotropic and fracture models.

## Decisions

1. Work proceeds in ordered milestones: data and import integrity; campaign and replicate reduction; persistence and accessible/mobile UX; analytical and FEM verification infrastructure; orthotropic model; fracture models. A later mechanics milestone cannot bypass a failed earlier gate.
2. A campaign contains a configuration and its individual physical specimens. One specimen is one independent replicate; rows within a CSV are repeated measurements of that specimen and never increase replicate count.
3. Each specimen’s modulus is the chord slope over engineering strain 0.0005 to 0.0025, following the project roadmap. Interpolate stress at the two strain boundaries and calculate `E = (sigma_0.0025 - sigma_0.0005) / (0.0025 - 0.0005)`. Record units, interval, sensor source, and any compliance correction with every reduction. A result without suitable gauge-strain data or a documented correction is explicitly uncorrected/exploratory and is ineligible for FEM validation.
4. Campaign mean is the arithmetic mean of specimen-level values; standard deviation is sample SD (`n - 1`); coefficient of variation is `100 * sample_SD / abs(mean)`. Report valid `n` for every metric. CoV is undefined when the mean is zero or there are fewer than two valid specimens. The roadmap’s minimum is five specimens per configuration: drafts with fewer than five remain usable, but cannot pass the campaign readiness/validation gate.
5. Upgrade workspaces to a versioned v2 schema. Read v1 workspaces through a migration that retains their raw rows, settings, and baseline result and labels unavailable provenance/metadata as missing; never fabricate it. Invalid workspaces fail with a field-specific error before state is changed or a saved file is overwritten.
6. Server-side optimistic concurrency uses a monotonically increasing study revision and `If-Match`. A stale write returns HTTP 409 with the current revision and preserves the local draft. The UI offers reload-current and save-as-copy actions; it does not silently overwrite or attempt a lossy automatic merge.
7. Study deletion is a recoverable soft delete, with a configurable retention period (default 30 days), restore during retention, and a clear permanent-purge action. Expired trash is purged by the storage service. API behavior and UI state must make active, trashed, and permanently deleted records distinguishable.
8. Numerical validation has three separate tiers: unit checks; solver verification against analytical/manufactured solutions and independent solvers; experimental validation against held-out specimens. An experimental comparison endpoint and UI stay disabled until all required verification checks pass for the exact solver/model configuration.
9. The requested mobile and accessibility checks are automated browser end-to-end coverage, not visual sign-off alone. The core flows are checked at mobile and desktop viewport sizes, by keyboard, and with automated accessibility rules.

## Data and provenance model

### Campaign and specimen

Introduce schema-versioned domain records (Pydantic models on the server and runtime guards in the browser):

- **Campaign:** stable ID, name, notes, creation/update timestamps, and one or more configurations. A configuration groups specimens by the controlled material/process variables intended for comparison (material and lot, printer/profile, raster/orientation, and relevant geometry). It exposes specimen count and readiness status.
- **Specimen:** stable ID/label, configuration ID, measured width/thickness/gauge length with units, print metadata, and one or more test runs. A duplicate specimen ID within a campaign is rejected.
- **Print metadata:** material/polymer and supplier/lot when known; printer and nozzle; layer height; raster/infill and build orientation; temperatures and other recorded process parameters; print date; and optional G-code/toolpath digest. Missing fields stay explicitly unknown rather than receiving defaults that look measured.
- **Test run:** test standard/revision when known, test date, operator, machine and load-cell identity/calibration, sensor source (extensometer, crosshead, clip gauge, DIC, or other with description), units, tension direction, compliance-correction method/value and calibration provenance, plus the specimen’s imported rows and analysis settings.
- **Input-file provenance:** original filename, media/format, byte count, SHA-256, import timestamp, and the test run/specimen that owns the file. Raw rows remain embedded in the study for v2; provenance hashes the exact imported bytes before parsing. A later external artifact store may deduplicate raw files without changing IDs or hashes.

### Result provenance

Every reduced or modeled result records the input-file digest(s), schema version, analysis settings and their digest, source revision and dirty state, dependency-lock digest, result digest, analysis timestamp, and algorithm/model version. Solver results additionally include container image digest, solver/library versions, mesh parameters and mesh digest, boundary-condition identifier, material-profile digest, and execution resources. Unknown values are represented as unavailable, never inferred from the current machine.

### Workspace compatibility

V2 uses the existing `styrkeanalyse-fdm-study` envelope with `version: 2`, a server-owned `revision`, campaign/specimen/test records, provenance, and derived results. Existing v1 study JSON remains importable and is migrated in memory; it is upgraded on an explicit successful save. Listing, reading, upload, analysis, and save all validate shapes and bounds. The browser must validate result structures before rendering, not just trust that `result` is an object. Malformed files produce actionable errors and cannot partially replace the current study.

## Import and analysis behavior

- Normalize CSV header names once and use the same normalized names as keys in every parsed row. Detect empty, duplicate-after-normalization, and ambiguous headers and explain the problem before column mapping.
- Header guessing returns “unmapped” when confidence is absent. Force and displacement must each map to an existing, distinct column before analysis. A mapping change invalidates the previous result until reanalysis.
- Positive dimensions are required and must be confirmed for the active specimen; implicit example/default values cannot mark specimen geometry as entered.
- Preserve the source bytes and hash before parsing. Surface parser warnings, missing selected-column cells, and non-finite/nonnumeric rows with row numbers; provide a preview of the rejected/omitted rows before analysis.
- A single-specimen tensile result carries the specimen metadata and its reduction. Campaign summaries are built only from one valid result per specimen and show `n/N`, mean, sample SD, and CoV for modulus and other supported metrics. Replicate summaries do not pool raw time-series samples.
- While analysis is in flight, bind the response to the exact inputs/settings revision submitted. If those inputs change, mark the returned result stale and do not present it as the current result.

## Persistence API and user experience

- Add ETag/revision information to study reads and list summaries; require `If-Match` on updates. A missing precondition receives a client error. A conflict returns 409 plus the current revision and update timestamp.
- Keep an edited draft after a conflict. “Reload current” requires a clear discard confirmation; “Save as copy” creates a new study ID and retains the draft. Do not offer a blind overwrite.
- Add delete-to-trash, restore, retention-policy read/update, and explicit purge routes. Validate IDs, apply the existing atomic file-replacement pattern, and keep corrupt records out of normal listings while exposing a recoverable storage error/log entry.
- Add study list controls for search/sort, restore, deletion, and retention visibility. Confirm destructive actions accessibly and announce success/errors to assistive technology.
- Preserve the current local-only binding and tailnet access assumption. Document that the application has no user-level authentication; do not broaden its bind address as part of this work.

## Verification and mechanics sequence

### Gate 1: analytical references

Implement independently derived analytical tensile and three-point-bending references plus hand-computed regression cases. Verify units, boundary conditions, compliance handling, and convergence of numerical calculations to the references. Add classical laminate theory (CLT) laminate stiffness (`A`, `B`, `D`) checks as the orthotropic analytical reference. Unit tests use exact expected values where arithmetic permits and stated tolerances where floating-point algorithms require them.

### Gate 2: isotropic FEM verification

Before an FEM/experiment comparison can run, the exact FEM build must pass and persist all of these checks:

1. Manufactured-solution mesh convergence with expected L2 order (P1 approximately `h^2`; P2 approximately `h^3`).
2. Uniform-stress patch test at the roadmap’s numerical tolerance.
3. Agreement with analytical tensile, bending, and applicable CLT references within the roadmap’s specified tolerances.
4. Independent CalculiX C3D10 displacement cross-check within the roadmap tolerance.

The gate record is immutable and tied to solver version, image digest, mesh family, material, boundary condition, and verification input digest. Any change to a tied configuration invalidates the gate. Verification failure blocks comparison and explains which check failed.

### Gate 3: orthotropic model

After Gate 2 passes, add the roadmap’s transversely isotropic model with five independent constants and an explicit local material frame aligned to the raster. Record the origin and uncertainty of each constant. Implement maximum-stress failure first, then Tsai-Wu with its `F12` assumption explicit. Cross-check against CalculiX. Freeze model/calibration choices before unblinding the held-out bend-bar configuration; compare predictions against replicate scatter only after the blind prediction is recorded.

### Gate 4: fracture models

Proceed in order: J-integral/LEFM post-processing; cohesive-zone law calibrated from DCB data; phase-field only after the cohesive and orthotropic validations are credible. Gate comparisons on mesh/objectivity checks and held-out notched-specimen peak load/crack path against experiment/photos or DIC. XFEM remains outside implementation scope per the roadmap.

If the repository’s available solver/container stack cannot meet a gate, record the missing capability and leave downstream model comparison disabled. Do not substitute a partially implemented solver or mark a gate passed from unit tests alone.

## UX, mobile, and accessibility acceptance

- The import-to-result workflow, saved-study workflow, conflict recovery, and trash/restore flow work end to end at a narrow phone viewport and desktop viewport without clipped primary controls or horizontal page overflow.
- At mobile widths, dense tables remain intentionally scrollable within their own labeled region; page navigation and key actions remain reachable without precision gestures.
- All controls have programmatic labels; keyboard focus is visible and order is coherent; dialogs trap/return focus correctly; status and errors use live announcements; color is not the only status signal; contrast meets WCAG AA; charts have a text summary and accessible tabular alternative.
- Automated axe checks report no serious/critical violations on import, configured-data, result, study-list, conflict, and delete/trash states. End-to-end tests exercise keyboard operation and assert expected focus behavior.
- Review on actual mobile/desktop browser emulation before completion; include viewport/browser details in the verification record.

## Regression coverage and definition of done

Regression suites cover: whitespace and duplicate CSV headers; original-header row-key mismatch; no-match and duplicate force/displacement mapping; dimension readiness and positivity; malformed JSON and malformed v1/v2 workspace fields, rows, settings, provenance, and result payloads; v1 migration round-trip; specimen/campaign ID and metadata validation; input SHA-256 stability; exact chord-modulus boundaries/interpolation; sample SD and CoV including `n < 2`, zero mean, missing specimens and `n < 5`; stale analysis response; concurrent edits and 409 recovery; soft delete/restore/expiry; every verification gate’s pass/fail/invalidation behavior; and mobile/accessibility end-to-end flows.

The feature is complete only when the application build, existing unit suites, new regression suites, browser end-to-end and accessibility suites pass; schema-v1 studies remain readable; and no comparison UI/API can bypass failed or stale solver verification. Scientific comparison remains unavailable if the required solver stack/data are not present.

## Risks and open implementation constraints

- The roadmap is documented against an older commit. Reconcile its existing assumptions with the current repository before treating a roadmap tolerance or solver capability as implemented.
- External testing standards may constrain the modulus/compliance procedure. Verify the chosen strain window, sensor requirements, and correction procedure against authoritative standards and the project’s equipment before labeling the result standards-compliant.
- DOLFINx/FEniCS versions use separate dependency environments in this repository. Keep solver dependencies/container images pinned and isolated; do not mix incompatible runtime generations.
- Automatic purge is irreversible. Retention changes, expired-item counts, and permanent deletion require clear UI feedback and regression coverage.
- Browser E2E and accessibility tooling may add a pinned browser dependency and CI runtime; keep it isolated from the scientific solver environment.
