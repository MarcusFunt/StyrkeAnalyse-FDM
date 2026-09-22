# StyrkeAnalyse-FDM

A research pipeline for testing how much FDM manufacturing information improves
strength and fracture predictions. The project will compare analytical statics,
conventional isotropic FEM, homogenised orthotropic FEM, and eventually local
G-code-informed material fields against measurements from printed specimens.

## What is implemented now

This first commit establishes a reproducible numerical environment rather than
pretending that a fracture solver already exists:

- DOLFINx/PETSc/MPI is the primary programmable FEM environment.
- CalculiX is installed as an independent reference solver.
- Gmsh provides mesh creation and the Python Gmsh API.
- `uv.lock` pins the ordinary Python analysis dependencies.
- Docker Compose and a VS Code Dev Container provide one canonical development
  environment for Windows + WSL2 users.
- `scripts/verify-environment.sh` verifies the scientific stack and runs tests.

The physical tensile/bending-rig data acquisition is intentionally outside the
container. It should write files such as CSV or Parquet; calibration and
simulation run in this environment.

The initial toolpath adapter uses the lightweight `gcodeparser` package. When
timing-aware printer-motion boundary conditions become relevant, add
`pyGCodeDecode` as a separately pinned Git dependency and record its commit in
the simulation provenance; it is not needed to establish the core FEM runtime.

## Quick start: Windows + WSL2

1. Install Docker Desktop with the WSL2 backend, then install the VS Code
   **Dev Containers** extension.
2. Clone the repository into the WSL filesystem (for example
   `~/projects/StyrkeAnalyse-FDM`), not under `/mnt/c`.
3. In the WSL terminal, run:

   ```bash
   export LOCAL_UID="$(id -u)"
   export LOCAL_GID="$(id -g)"
   docker compose build
   docker compose run --rm dev scripts/verify-environment.sh
   ```

4. Open the repository in VS Code and choose **Dev Containers: Reopen in
   Container**. The post-create step repeats the environment verification.

For interactive shell access:

```bash
docker compose run --rm dev bash
fdm-strength info
```

## Reproducibility rule

Before generating results for the SOP, replace the default `stable` DOLFINx
image with an exact release/digest in `.env`, rebuild, and commit that change:

```dotenv
DOLFINX_IMAGE=ghcr.io/fenics/dolfinx/dolfinx:<verified-release-or-digest>
```

The container image plus `uv.lock`, the input STL/G-code checksums, material
profile, mesh size and git commit should be recorded with every simulation.

## Planned pipeline

```text
STL + slicer G-code
        ↓
normalised ToolpathModel
        ↓
mesh/material-field mapping
        ↓
analytical | PyNite | DOLFINx | CalculiX
        ↓
prediction vs experimental force/displacement/failure location
```

## Repository layout

```text
src/fdm_strength/      Python package and command-line interface
tests/                 Fast, solver-independent tests
docker/Dockerfile      Scientific analysis image
.devcontainer/         VS Code Dev Container definition
scripts/               Reproducible verification commands
```

## What comes next

`docs/roadmap-first-accurate-results.md` audits the current implementation and
sets out the critical path to a first validated prediction, including the
verification gates that must pass before any comparison against measurements.
It is written against the project's 86-entry source review and maps each step
back to its references. `docs/reference-implementations.md` covers the existing
open-source projects each milestone can build on, with licences and measured
effort estimates, and `docs/execution-environments.md` covers how those
mutually incompatible dependency sets are split across containers.
`docs/glossary.md` explains the terminology all three use, with a compact
lookup table at the end.

1. Declare a unit convention, the canonical data schema and a provenance record.
2. Add analytical tensile and three-point-bend reductions as the solver oracle.
3. Add classical laminate theory as the cheap anisotropic stiffness baseline.
4. Print and test the full specimen matrix: elastic and strength coupons,
   notched fracture specimens, and interlayer DCB.
5. Add a DOLFINx isotropic baseline with a CalculiX cross-check, behind an
   explicit verification gate.
6. Add the orthotropic model and failure index, then the fracture tier.
7. Compare G-code-derived material fields against CAD geometry as a controlled
   experiment, not as an assumed improvement.

The printed specimens are the schedule driver, so design the whole matrix and
start that campaign alongside the software work rather than after it.
