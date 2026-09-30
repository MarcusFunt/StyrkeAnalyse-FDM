# Pre-rig software completion plan

## Context

The physical tensile/bending rig is not ready yet because parts are still in transit. Until the hardware is available, the project should use the waiting time to finish the software path that would otherwise block or slow down the experimental campaign.

The goal is **not** to keep adding generic infrastructure indefinitely. The goal is to reach a state where, once the rig exists, the remaining work is primarily:

1. calibrate the physical setup,
2. print specimens,
3. collect measurements,
4. import data,
5. run already-implemented calibration/simulation workflows,
6. compare predictions against held-out measurements.

The software should therefore be completed in the order that removes future experimental bottlenecks.

---

## Definition of "software ready before the rig arrives"

The pre-rig software phase is complete when the repository can perform the following end-to-end workflow using synthetic data:

```text
synthetic specimen + synthetic material truth
        ↓
synthetic raw measurement files
        ↓
normal experiment ingestion
        ↓
replicate reduction and uncertainty
        ↓
material-profile calibration
        ↓
verified isotropic FEM
        ↓
orthotropic FEM
        ↓
held-out prediction artifact
        ↓
synthetic unblinding
        ↓
prediction-error report
```

The same path must later accept real rig files without changing the scientific architecture.

---

# Priority 0 — resolve the current runner/provenance branch

## Goal

Merge the runner/provenance architecture before building additional solver stages on top of it.

## Work

- Rebase/update PR #7 onto current `main`.
- Resolve overlap with the newer solver-provenance/toolpath work already on `main`.
- Preserve:
  - immutable scientific Run records,
  - content-addressed artifacts,
  - persistent asynchronous jobs,
  - server-owned stage definitions,
  - fail-closed restart behavior,
  - formal image provenance,
  - explicit CPU/thread/MPI policies,
  - campaign reduction from immutable upstream results.
- Re-run the full Verify workflow after the rebase.
- Merge only once the branch is based on current `main` and CI is green.

## Done when

- PR #7 is no longer diverged from `main`.
- Verify passes.
- There is one canonical runner/stage/provenance architecture for all later FEM work.

---

# Priority 1 — implement the first formal isotropic FEM stage

## Goal

Create the first real solver stage that produces a reproducible FEM result rather than only reference calculations and verification metadata.

## Suggested stage

`fdm-l2-isotropic`

## Inputs

At minimum:

- specimen geometry,
- mesh settings,
- isotropic material profile,
- load/boundary-condition definition,
- requested quantities of interest.

The stage contract should carry the exact immutable identities needed for replay.

## Solver path

- Gmsh for mesh generation.
- DOLFINx for the primary solution.
- Baked formal stage image, not a bind-mounted development tree.
- Network disabled during formal execution.
- Explicit MPI rank / OMP / BLAS thread policy.

## Required provenance

Populate the existing solver-oriented fields rather than introducing another parallel metadata format:

- solver name,
- solver version,
- mesh artifact hash,
- mesh generation parameters,
- material-profile ID and hash,
- boundary-condition-set ID/hash,
- stage image ID,
- base-image reference/digest,
- git commit / dirty state,
- dependency-lock hash,
- input/output artifact hashes,
- CPU/thread/MPI settings,
- timestamps/runtime versions.

## Initial quantities of interest

Support at least:

- reaction force,
- displacement,
- nominal stress/strain,
- displacement field,
- stress field,
- peak scalar stress,
- basic energy quantities needed by verification.

## Done when

A formal Run can take a simple tensile specimen definition, generate a mesh, solve it with DOLFINx, persist all artifacts, and replay from immutable inputs.

---

# Priority 2 — make the isotropic FEM verification gate actually green

The existing fail-closed gate is useful only once real solver evidence exists.

## Required verification evidence

### 1. Manufactured-solution / convergence evidence

Run a convergence study with a problem where the expected solution is known.

Store:

- mesh sizes,
- error norm,
- observed convergence rate,
- solver configuration,
- result artifact hashes.

### 2. Uniform-stress patch test

Use a geometry/load case where a uniform stress state should be recovered.

Check:

- displacement,
- stress uniformity,
- reaction-force consistency,
- tolerance against the analytical solution.

### 3. Analytical agreement

Compare the FEM result against existing repository reference calculations for simple cases such as:

- axial tensile loading,
- three-point bending where appropriate.

### 4. Independent CalculiX cross-check

Solve the same case with CalculiX using the same nominal geometry/material/load assumptions.

Compare defined quantities of interest rather than screenshots.

## Important implementation rule

The GUI must not expose FEM-vs-experiment conclusions unless the relevant solver verification assessment is green.

## Done when

- all four evidence records exist,
- the existing verification evaluator accepts them,
- the gate reports comparison allowed,
- CI contains regression coverage preventing a solver-stage change from silently bypassing the gate.

---

# Priority 3 — integrate simulation jobs into the GUI

## Goal

Make the browser GUI capable of driving the scientific solver workflow before real measurements arrive.

## Required GUI functionality

### Model setup

Allow selection/editing of:

- geometry/specimen,
- material profile,
- mesh parameters,
- boundary/load case,
- solver stage.

### Job execution

Use the asynchronous runner introduced by PR #7:

- queued,
- running,
- succeeded,
- failed.

Show failure reasons and retained provenance.

### Result inspection

Display at least:

- scalar summary values,
- convergence/verification status,
- mesh metadata,
- displacement/stress field result availability,
- solver provenance,
- artifact links/identities.

### Safety/semantics

- Solver verification state must be visually separate from experimental replicate readiness.
- Do not label replicate-ready data as validated.
- Do not allow a missing M4 gate to appear as a warning-only condition.
- Preserve immutable Run identity when reopening saved studies.

## Done when

A user can launch and inspect a formal isotropic simulation entirely through the GUI and can see why a result is or is not eligible for experimental comparison.

---

# Priority 4 — implement the orthotropic FEM path

## Goal

Turn the existing orthotropic constitutive/failure-reference code into an actual solver material path.

## Material representation

Keep the repository's general engineering-constant representation as canonical.

Support at minimum:

- `E1`,
- `E2`,
- `E3`,
- `nu12`,
- `nu13`,
- `nu23`,
- `G12`,
- `G13`,
- `G23`.

Do not collapse this into a simpler transversely-isotropic representation at the schema level even if some early fits use tied parameters.

## Solver behavior

- assign material axes explicitly,
- solve using the same geometry/load-case contract as isotropic FEM,
- produce the same core quantities of interest,
- emit failure-index fields where applicable.

## Failure criteria

Keep the currently implemented reference methods available:

- maximum stress,
- Tsai-Wu.

Treat assumptions such as `F12` as explicit configuration/provenance, not hidden constants.

## Cross-checks

- analytical/CLT fixtures where applicable,
- CalculiX engineering-constants material card,
- orientation sanity tests.

## Done when

The same specimen can be solved using isotropic and orthotropic material profiles through the same formal execution path and compared with controlled inputs.

---

# Priority 5 — build the material-calibration pipeline using synthetic data

## Goal

Make real material calibration an input-data problem rather than a software-development problem.

## Calibration workflow

The calibration layer should:

1. select eligible immutable experimental Runs,
2. identify which specimen orientations/configurations constrain which parameters,
3. fit a material profile,
4. record uncertainty / fit diagnostics,
5. persist the resulting material profile as an immutable artifact,
6. link the calibration profile to the source Runs that produced it.

## Before real data exists

Create synthetic campaigns with known ground-truth parameters and verify that the calibration code can recover them within expected noise/tolerance.

Synthetic campaigns should include realistic features:

- measurement noise,
- specimen-to-specimen scatter,
- small geometry variation,
- occasional invalid runs,
- multiple orientations,
- explicit train/calibration vs held-out split.

## Done when

A generated synthetic tensile campaign can produce an immutable fitted material profile that is then consumed by FEM without manual copy/paste.

---

# Priority 6 — freeze the rig data contract before firmware is finished

## Goal

Define what the future physical test rig must emit so software and firmware do not evolve independently.

## Raw run data

Define a versioned machine-readable format for at least:

- timestamp or sample index,
- force,
- actuator/crosshead displacement,
- extensometer/camera-derived strain if available,
- temperature if measured,
- status/event markers.

Prefer raw SI-adjacent engineering units already used by the project:

- mm,
- N,
- MPa where derived.

Do not store only processed stress/strain curves.

## Run manifest

Every raw file should have a corresponding manifest containing at least:

- schema version,
- specimen ID,
- test type,
- machine/rig ID,
- load-cell calibration ID,
- displacement/strain-sensor calibration ID,
- acquisition rate,
- controller/firmware revision,
- test-standard/revision,
- operator/setup metadata where scientifically relevant,
- raw-file hash.

## Calibration records

Force/displacement/extensometer calibration should be separate immutable records referenced by Runs rather than copied loosely into notes.

## Done when

A synthetic rig exporter can write exactly the file/manifest pair that the real firmware/controller will later emit, and the existing GUI/runner can ingest it unchanged.

---

# Priority 7 — run a complete synthetic experiment

This is the integration test for the entire pre-rig software phase.

## Scenario

Use a known synthetic PLA-like material truth to generate:

- at least five tensile specimens per important configuration,
- realistic noise/scatter,
- a calibration set,
- a held-out bending set.

## Required end-to-end steps

1. Generate raw synthetic measurement files.
2. Import them through the normal experimental path.
3. Reduce one result per physical specimen.
4. Aggregate replicate statistics.
5. Fit a material profile.
6. Freeze the fitted profile.
7. Run isotropic FEM.
8. Run orthotropic FEM.
9. Create a held-out bending prediction **before** exposing the synthetic truth.
10. Persist the prediction artifact.
11. Unblind the held-out synthetic data.
12. Calculate prediction error and uncertainty.
13. Produce a comparison report/artifact.

## Why this matters

This exposes integration holes while they are cheap to fix.

It should reveal problems such as:

- schema mismatches,
- missing provenance links,
- GUI paths that require manual state,
- calibration inputs that are not immutable,
- solver outputs that cannot be compared consistently,
- hidden assumptions in units/orientations,
- unblinding that can accidentally contaminate a prediction.

## Done when

The whole workflow can be repeated from a clean checkout/container state without editing result files manually.

---

# Priority 8 — finish the useful part of the G-code path

The current toolpath parser is the first M7 data layer. Continue only far enough to make it usable in the later controlled comparison.

## Implement next

```text
G-code
  ↓
ToolpathModel
  ↓
register toolpath to specimen coordinates
  ↓
derive local deposition/raster direction
  ↓
map direction/orientation onto FEM elements
  ↓
generate local material axes
  ↓
solve with otherwise fixed orthotropic constants
```

## Explicitly defer

Until real calibration data exists, do not spend major effort inventing:

- bead-strength correction laws,
- porosity-strength relationships,
- empirical bonding coefficients,
- highly parameterized local fracture laws.

Those can only be justified once measurements exist.

## Controlled comparison to preserve

Later, compare:

1. homogeneous/isotropic CAD FEM,
2. homogeneous orthotropic FEM,
3. local G-code-informed orientation FEM,

while holding everything else fixed.

The research question is whether adding manufacturing information improves prediction accuracy. A negative result must remain a valid outcome.

## Done when

A specimen's parsed G-code can deterministically generate element/material-axis orientation data consumed by the orthotropic solver.

---

# Priority 9 — keep fracture work intentionally bounded

## Safe pre-rig work

It is reasonable to finish:

- fracture data schemas,
- notched-specimen geometry support,
- analytical LEFM/J-integral reference calculations,
- solver interfaces/stubs,
- verification fixtures that do not require fitted fracture parameters.

## Defer until physical fracture data exists

Do not make these a prerequisite for the core project:

- cohesive-zone calibration,
- DCB-fitted interlayer fracture laws,
- phase-field parameter fitting,
- anisotropic fracture-energy identification,
- large fracture-model parameter sweeps.

The core SOP should already succeed with tensile calibration + held-out bending prediction.

---

# CI / regression requirements

Before the rig arrives, CI should cover three distinct classes of correctness.

## Fast analytical/data tests

- units,
- data migrations,
- reduction,
- replicate statistics,
- CLT,
- orthotropic constitutive calculations,
- failure criteria,
- toolpath parsing,
- calibration fitting with synthetic fixtures.

## Solver verification tests

Use appropriately small cases in CI where practical:

- patch test,
- simple analytical agreement,
- provenance completeness,
- deterministic solver-contract validation.

Large convergence/cross-solver studies may remain retained artifacts from formal verification runs rather than every-commit CI jobs.

## End-to-end tests

At least one automated path should exercise:

```text
synthetic raw test file
→ formal reduction Run
→ campaign aggregation
→ material calibration
→ formal FEM Run
→ prediction artifact
→ comparison report
```

The browser E2E suite should exercise the same user-visible workflow at a reduced scale.

---

# Suggested implementation sequence

Use this order unless a hard dependency requires otherwise:

```text
1. Resolve + merge PR #7
2. Formal isotropic FEM stage
3. Produce all M4 verification evidence
4. GUI simulation-job workflow
5. Orthotropic FEM material adapter
6. Synthetic material calibration
7. Freeze rig raw-data + manifest schema
8. Full synthetic blind-prediction campaign
9. G-code → local orientation mapping
10. Optional pre-rig fracture scaffolding
```

This ordering deliberately places scientific execution and verification ahead of additional orchestration work.

---

# What not to spend time on before the rig arrives

Unless a concrete blocker appears, avoid expanding into:

- Kubernetes,
- distributed scheduling,
- generic plugin systems,
- additional database infrastructure,
- large-scale RVE/voxel pipelines before the simpler orthotropic path works,
- advanced fracture calibration without fracture measurements,
- speculative ML predictors without a real dataset.

The project already has enough infrastructure to justify moving toward actual scientific computation.

---

# Exit criteria for the waiting period

The software waiting period is successful if, when the hardware arrives, the following statement is true:

> A physical specimen can be assigned an ID, tested by the rig, emitted as a versioned raw file plus calibration-linked manifest, imported without schema changes, reduced into immutable experiment Runs, used to fit a material profile, passed directly into already-verified FEM stages, and compared against a held-out prediction through the existing GUI.

At that point the project has moved from **building a platform for doing science** to having a platform that is ready to perform the real SOP experiment.
