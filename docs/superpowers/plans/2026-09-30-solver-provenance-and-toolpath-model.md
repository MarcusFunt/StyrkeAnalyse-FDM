# Solver Provenance and Toolpath Model Implementation Plan

> **For agentic workers:** Implement the tasks in order in the current checkout. Keep the M4 solver comparison gate fail-closed.

**Goal:** Complete the M0 stage-provenance foundation and immutable DOLFINx image pin, then add a normalized G-code toolpath model as the first M7 deliverable.

**Architecture:** Extend the immutable Run/Stage records and the file-based stage contract so each execution records its exact runtime image, dependency lock, command, resource counts, inputs, outputs, and timestamps. Add a solver-independent `ToolpathModel` that hashes original G-code bytes, applies supported modal movement state, and emits normalized millimeter deposition moves; unsupported curved or coordinate-system-changing motion fails with a line-specific error.

**Tech Stack:** Python 3.12, Pydantic 2, Docker, `gcodeparser` 0.3.0 (already locked), uv.

**Spec:** `docs/execution-environments.md` §4 and §7; `docs/roadmap-first-accurate-results.md` M0 and M7.

## Global Constraints

- Store provenance as an immutable, versioned record and keep old saved Run records readable.
- Record `mpi_ranks` and `omp_threads` for each stage.
- Use immutable image references for solver base images; never describe a moving tag as pinned.
- Preserve the exact source G-code SHA-256 and keep G-code interpretation separate from per-element FEM mapping.
- Keep all experimental comparison paths disabled until the matching M4 gate is complete and passing.
- Do not claim solver verification or experimental validation from parsing or analytical code.

## Review Focus

- Older persisted Run records missing newly introduced provenance fields remain readable.
- A run cannot succeed if its stage provenance disagrees with the immutable stage contract or artifacts.
- Relative/absolute XYZ and E modes, inch/mm changes, tool changes, G92 resets, and empty moves do not silently corrupt deposition direction.
- G2/G3 arcs and unsupported coordinate transforms fail with a source line number rather than becoming straight segments.
- G-code files with a valid hash but unsupported text encoding fail before producing a partial model.

---

### Task 1: Complete M0 stage provenance and pin the solver base image

**Files:**
- Create: `src/fdm_strength/provenance.py`
- Modify: `src/fdm_strength/run_models.py`, `src/fdm_strength/stage_contract.py`, `src/fdm_strength/runner_service.py`, `src/fdm_strength/exp_reduction_stage.py`, `src/fdm_strength/cli.py`
- Modify: `docker/Dockerfile`, `docker/exp-reduction.Dockerfile`, `compose.yaml`, `.env.example`, `pyproject.toml`
- Modify: `docs/execution-environments.md`, `docs/roadmap-first-accurate-results.md`

**Interfaces:**
- `StageProvenance` is a strict frozen model with schema version, run/stage identity, operation, image and base-image references, dependency-lock SHA-256, entrypoint, input/output artifact digests, git state, MPI/OpenMP counts, and timezone-aware start/finish timestamps.
- `StageRecord` carries the execution identity and resource fields and remains backward-compatible with records written before these fields existed.
- `StageContract` carries the pinned image identity, safe argv entrypoint, dependency-lock SHA-256, `mpi_ranks`, and `omp_threads`; the executor applies the thread count to the container environment.
- Pin DOLFINx to `ghcr.io/fenics/dolfinx/dolfinx:v0.11.0@sha256:2ae4bfbc0d9077268880faf04c72750528bee986c94ab223a2c159969bd56fa8` (official multi-platform package digest).

- [x] Add the versioned provenance model and thread/resource fields while preserving v1 record loading; make `inspect` hash exact input bytes.
- [x] Build the complete stage provenance from the validated contract, immutable resolved image ID, dependency lock, image labels, artifact digests, and stage timestamps bounded by executor timestamps.
- [x] Reject a successful stage when its provenance differs from its contract or when required digests/resource metadata are absent.
- [x] Set and record `OMP_NUM_THREADS`; record the current single-process stage as one MPI rank and one OMP thread.
- [x] Pin and label the DOLFINx base image; expose solver, mesh, material-profile, and boundary-condition metadata fields for FEM stages.
- [x] Add a CLI report that resolves and verifies stored Run provenance artifacts; update execution-environment and roadmap status without claiming Gate M4 passed.
- [x] Defer verification; do not add or run tests in this change.

### Task 2: Add normalized G-code toolpath records

**Files:**
- Create: `src/fdm_strength/toolpath.py`
- Modify: `docs/roadmap-first-accurate-results.md`, `README.md`

**Interfaces:**
- `parse_toolpath(source_bytes: bytes) -> ToolpathModel` parses exact imported bytes and reports their SHA-256 and size.
- `ToolpathModel` contains schema version, parser/version, millimeter coordinate convention, deposition moves, bounding box, and explicit warnings/unsupported cases.
- Each immutable move stores source line, tool/layer when available, start/end coordinates in mm, filament extrusion delta, feed rate in mm/min, path length, 3D unit direction, and in-plane raster angle modulo 180 degrees when defined.

- [x] Parse using the locked `gcodeparser` API and apply G20/G21, G90/G91, M82/M83, T-tool selection, modal feed/motion, and G92 extrusion/coordinate resets.
- [x] Separate positive-extrusion spatial moves from travel/retraction moves; never infer local porosity or bead width from missing G-code data.
- [x] Reject G2/G3 arcs and unsupported coordinate transforms with physical source line numbers.
- [x] Keep the M7 model as an input to future per-element field mapping; do not connect it to FEM or comparison UI in this task.
- [x] Document implemented scope and remaining prerequisites, including M4 verification and specimen/toolpath registration.
- [x] Defer verification; do not add or run tests in this change.
