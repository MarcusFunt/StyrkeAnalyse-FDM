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

1. Define specimen YAML files and the canonical `ToolpathModel` data schema.
2. Implement and test a G-code normaliser for one controlled slicer profile.
3. Add M0 analytical tensile and three-point-bend predictions.
4. Add a simple DOLFINx isotropic baseline and a CalculiX cross-check.
5. Add orthotropic calibration coupons before attempting local G-code fields.
