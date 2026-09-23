# Jupyter container framework design

## Goal

Provide a local, free, reproducible notebook workflow for the SOP without forcing incompatible FDM modelling dependencies into one Python installation.

## Scope

The first implementation creates exactly three Compose services:

| Service | Responsibility | Base environment |
| --- | --- | --- |
| `analysis` | Baseline statics, experimental-data reduction, plots and ordinary package tests | Python 3.12 slim |
| `fenicsx` | Orthotropic and G-code-informed continuum FEA; CalculiX cross-checks | Existing DOLFINx/PETSc/MPI environment |
| `rve` | G-code/voxel and homogenisation experiments | Python 3.10 |

Each service exposes JupyterLab only when it is explicitly started, mounts the same source tree, and writes to the same `data/`, `results/`, and `notebooks/` folders. Services remain independent; the notebook is an interactive front end, while reusable modelling code belongs in `src/fdm_strength/`.

## Non-goals

This change does not install VOLCO, fedoo, fibergen, PhaseFieldX, or legacy FEniCS. Those tools must be evaluated and pinned independently before they enter an image. The RVE image provides the compatible Python 3.10 dependency universe and a testable extension point; it must not claim that a solver works before it has been added and verified.

DIC, legacy fracture, and specialised homogenisation images remain future additions described in `docs/execution-environments.md`.

## Interfaces and behaviour

- `docker compose run --rm analysis test` runs the solver-independent package test suite.
- `docker compose up analysis` starts JupyterLab at `http://localhost:8888`.
- `docker compose up fenicsx` starts a second JupyterLab at `http://localhost:8889`.
- `docker compose up rve` starts a third JupyterLab at `http://localhost:8890`.
- Jupyter binds to `127.0.0.1` and uses a token configured by `.env`; it must never default to a LAN-accessible unauthenticated server.
- The existing `dev` service is renamed to `fenicsx`, preserving its DOLFINx, CalculiX, Gmsh, and verification behaviour.
- A new `scripts/verify-compose-config.sh` validates Compose rendering and asserts the service invariants without needing to download multi-gigabyte images.
- An example notebook runs in `analysis`, imports a small reusable module, calculates nominal tensile stress, and makes a plot. It is deliberately a workflow check, not a scientific validation result.

## Reproducibility

Development services bind-mount the repository. Formal simulation runs must continue to use baked images and the provenance rule in `docs/execution-environments.md`; mounting source is for exploration only. Image names, base-image tags, project Python constraints, and package locks are version controlled. The README must label the exact commands as development workflow and state that a notebook is reproducible only when restarted and run top-to-bottom.
