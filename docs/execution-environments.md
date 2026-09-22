# Execution environments: one container per dependency universe

The tool survey in `reference-implementations.md` settles this question: the
projects worth building on cannot share a Python environment. Isolating them in
containers is not over-engineering, it is the only thing that works.

This document records the image split, the data contract between stages, what
that means for provenance, and an honest assessment of which orchestrator is
worth the trouble.

---

## 1. Why the dependency conflicts are real

These are measured from the repositories, not assumed:

| Project | Requires | Conflicts with |
| --- | --- | --- |
| PhaseFieldX | `fenics-dolfinx==0.11.0` | everything below in this block |
| comet-fenicsx | DOLFINx 0.8.0 | DOLFINx 0.11 |
| anisotropic_phase-field_fracture | legacy FEniCS (`from dolfin`) | both DOLFINx versions |
| GPFniCS, Maurini `damage-course` | legacy FEniCS | both DOLFINx versions |
| VOLCO | Python 3.8–3.10 (stated in README) | DOLFINx images shipping newer Python |
| fibergen | C++/OpenMP build + Python bindings | its own toolchain |
| fedoo (+ simcoon) | own Python stack | — |
| muDIC | Numba, older Python | newest Python |
| pyxel | VTK | — |
| dolfinx_materials | DOLFINx + TFEL/MFront + MGIS | adds a compiled toolchain |

There are **three mutually exclusive FEniCS universes** in that list — legacy
2019.1, DOLFINx 0.8, DOLFINx 0.11 — and no amount of virtualenv discipline
reconciles them. The Python-version squeeze is independent and just as hard:
VOLCO caps at 3.10 while the current DOLFINx images ship newer interpreters, and
`pyproject.toml` already declares `>=3.10,<3.13`.

So: separate images, and a way to pass data between them. That decision is
forced.

---

## 2. Split by dependency universe, not by experiment

One image per experiment would mean rebuilding for every parameter sweep. What
actually varies is the *dependency set*, and there are six of those:

| Image | Contains | Used by |
| --- | --- | --- |
| `fdm-analysis` | Python + project package only; no solver | M1 analytical, M2 CLT, M3 data reduction, plots, **CI** |
| `fdm-core` | DOLFINx 0.11 + PETSc/MPI + Gmsh + CalculiX + PhaseFieldX | M4, M5, M6 (J-integral, CZM, isotropic phase-field) |
| `fdm-voxel` | Python 3.10 + VOLCO + ciclope + meshio | M7 G-code → voxels → `.inp`/STL |
| `fdm-homog` | fedoo (+ simcoon), or fibergen | RVE → effective 6×6 |
| `fdm-dic` | muDIC + pyxel + VTK | DIC and identification |
| `fdm-legacy-pf` | FEniCS 2019.1 + anisotropic phase-field | M6 anisotropic arm **only if pursued** |

Notes on the split:

- **`fdm-analysis` is the one that matters most day to day.** It is small, fast,
  and has no solver, so it can run the `unit` test tier in CI and on any machine.
  Everything that does not need a PDE solved should run here. Keeping this image
  solver-free is a design constraint worth defending.
- **comet-fenicsx gets no image.** Rather than maintain a DOLFINx 0.8
  environment for it, port the tours forward into `fdm-core` as you adopt them.
  You are rewriting them for 3D and for the project schema anyway.
- **`fdm-homog` may split in two.** fedoo is pure Python; fibergen is a C++ build.
  If they will not co-install cleanly, make them separate images — running both
  on the same voxel array and comparing is a feature, not a problem.
- **`fdm-legacy-pf` is conditional.** Build it only if the anisotropic phase-field
  arm survives the decision in `reference-implementations.md` §6.

---

## 3. The data contract is the actual design work

Once stages live in different containers they cannot share Python objects. Every
boundary becomes a file, so the file formats *are* the architecture. Get this
right and the orchestrator becomes an implementation detail; get it wrong and no
orchestrator saves you.

**Every stage obeys the same contract:**

```text
/work/in      read-only    inputs (previous stage's outputs, raw data)
/work/out     read-write   outputs, including provenance.json
/work/run.json             the run specification for this stage
```

and is invoked as a single CLI command with no interactive state:

```bash
docker run --rm \
  -v "$RUN/in:/work/in:ro" -v "$RUN/out:/work/out" \
  fdm-voxel:<digest> \
  fdm-voxel gcode-to-rve --spec /work/run.json
```

**Formats, fixed now:**

| Data | Format | Why |
| --- | --- | --- |
| Scalars, metadata, specs | JSON (pydantic-validated) | diffable, schema-checked |
| Tabular (test runs, sweeps) | Parquet | typed, compressed, hashable |
| Meshes | `.msh` (Gmsh) / `.inp` (CalculiX) | native to both solvers |
| Fields | XDMF + HDF5, or VTU | ParaView-readable from either solver |
| Voxel arrays | `.npz` or Zarr | VOLCO's native output shape |
| Material constants | JSON, full 6×6 plus derived engineering constants | never store only `E1, E2, …` |

That last row matters: store the **full stiffness matrix**, not just the
engineering constants derived from it. The derivation is lossy if the material
turns out not to fit the transversely-isotropic reduction, and you will want to
check whether it does.

**Consequence for M0:** the pydantic schema is no longer an internal
convenience, it is a published inter-process interface. It therefore needs a
`schema_version` field from the first commit, and a test that old fixtures still
load. This raises the value of the M0 work rather than lowering it.

---

## 4. Provenance becomes a DAG, not a single record

The roadmap's M0 provenance record assumes one container produced the result.
With a stage pipeline that is no longer true, and "the image digest" is
ill-defined. The record needs to become a list of stages:

```json
{
  "run_id": "...",
  "schema_version": "1.0",
  "git_commit": "...", "git_dirty": false,
  "stages": [
    {
      "name": "gcode_to_voxel",
      "image": "ghcr.io/…/fdm-voxel@sha256:…",
      "entrypoint": ["fdm-voxel", "gcode-to-rve", "--spec", "/work/run.json"],
      "inputs":  [{"path": "specimen.gcode", "sha256": "…"}],
      "outputs": [{"path": "voxels.npz",     "sha256": "…"}],
      "mpi_ranks": 1,
      "omp_threads": 1,
      "started": "…", "finished": "…"
    }
  ]
}
```

Three details that are easy to miss and expensive later:

1. **Record `mpi_ranks`.** PETSc iterative solves are not bit-identical across
   different rank counts. A result reproduced on a different number of ranks can
   differ in the last digits, and if you have not recorded the count you cannot
   explain the discrepancy. Record `omp_threads` for the same reason.

2. **A bind-mounted source directory breaks the digest guarantee.** The current
   `compose.yaml` mounts `.` into the container, which is correct for
   development and wrong for producing results: the image digest no longer
   determines the code that ran. Result runs must use an image with the code
   **baked in**, mounting only data. Keep both modes and make them visibly
   different:

   ```yaml
   services:
     dev:   # bind-mounts source, for editing
     run:   # no source mount, code baked in, for results
   ```

   This is the mechanism that actually enforces the README's reproducibility
   rule, which is currently a sentence rather than a constraint.

3. **Pin every image by digest, not tag** — the same rule the roadmap already
   applies to `DOLFINX_IMAGE`, now multiplied by six.

---

## 5. Kubernetes: probably not yet, and the decision is reversible

Containers: unambiguously right. Kubernetes specifically: worth questioning.

**What Kubernetes gives you here:** multi-node scheduling, a job queue with
retries, resource limits, and parallel fan-out.

**What it costs:** a control plane, manifests, persistent volume claims and
storage classes, an image registry, RBAC, and a failure surface that has nothing
to do with FDM mechanics. When a pod fails, diagnosing it is slower than
diagnosing a failed `docker run`. On a single workstation — which is what the
README's Windows + WSL2 setup describes — that is overhead against no benefit.

**Where it genuinely earns its place**, and you do have candidates:

- A **real multi-node cluster** is available (school or university). If so, the
  calculus changes completely and K8s is the right answer.
- An **embarrassingly parallel sweep** large enough to matter. The mesh
  convergence study in M4 is exactly this: 5 mesh densities × 2 element orders ×
  2 solvers is 20 independent jobs. Phase-field runs are long. A DIC campaign
  over many image pairs is the same shape.

Even then, note that **multi-node MPI on Kubernetes needs an MPI operator**, and
DOLFINx is an MPI code. At this problem size you almost certainly want one pod
running `mpirun -n N` on a single node anyway, which K8s handles fine but which
also means you are not using the part of K8s that justified the complexity.

**The recommendation is to make the decision late, and cheap.** Build the images
and the CLI contract in §3 now — they are needed under any orchestrator. Run
them with Compose plus a `Makefile` or `justfile` on your own machine. If a
cluster appears, a K8s `Job` manifest per stage is a thin wrapper over the exact
same `docker run` invocation: `image`, `command`, two volume mounts. That is a
config addition, not a rewrite.

If Kubernetes is partly a **learning goal** for the project, that is a legitimate
reason — but declare it as one. The SOP is assessed on the mechanics and the
validation design, so orchestration complexity that is not carrying weight is a
cost against the part being graded.

---

## 6. Practical warnings

- **Image size.** DOLFINx images are multi-gigabyte. Six variants is tens of
  gigabytes. Share a base layer where the dependency sets allow, build only the
  images an arm actually needs, and run a local registry rather than rebuilding.
- **Build them one at a time, against a real task.** Do not build all six up
  front. `fdm-voxel` first, because running VOLCO on real G-code in week one
  tells you whether the M7 arm is feasible at all.
- **Threading determinism.** `OMP_NUM_THREADS: 1` is already set in
  `compose.yaml` and is correct. Set `OPENBLAS_NUM_THREADS` too — NumPy's BLAS
  will otherwise thread independently and change reduction orders.
- **Containers hide non-determinism, they do not remove it.** Pin digests, fix
  thread and rank counts, seed anything stochastic, and record all of it.
- **The separation has a licensing side benefit.** GPL-3.0 tools (VOLCO, fedoo,
  fibergen, FullControl) end up in their own images, invoked as processes rather
  than linked as libraries. Licensing is not a constraint on this project, but
  the boundary is free and worth keeping tidy.

---

## 7. What to change in the repository

In rough order:

1. Split `compose.yaml` into `dev` (bind-mounted, for editing) and `run`
   (code baked in, data-only mounts).
2. Pin `DOLFINX_IMAGE` to a digest — already required by roadmap §1.3.
3. Define the stage CLI contract (`--spec /work/run.json`, `/work/in`,
   `/work/out`) and add `schema_version` to the pydantic models in M0.
4. Extend `provenance.py` to the per-stage record in §4, including `mpi_ranks`
   and `omp_threads`.
5. Build `fdm-analysis` and `fdm-core` first; add `fdm-voxel` when M7 starts.
6. Add a `Makefile` with one target per stage, so the orchestrator is a
   one-line change later.
7. Revisit Kubernetes when either a cluster or a real sweep exists.

The Dockerfile sketches implied above have not been built or tested in this
environment — treat them as a plan, not a working configuration.
