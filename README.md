# StyrkeAnalyse-FDM

A research pipeline for testing how much FDM manufacturing information improves
strength and fracture predictions. The project will compare analytical statics,
conventional isotropic FEM, homogenised orthotropic FEM, and eventually local
G-code-informed material fields against measurements from printed specimens.

## What is implemented now

The project currently has three local development environments:

- `analysis` provides Python 3.12, scientific Python, JupyterLab, and the
  solver-independent test suite.
- `fenicsx` provides DOLFINx/PETSc/MPI, CalculiX, Gmsh, and JupyterLab.
- `rve` provides Python 3.10 and JupyterLab as an extension point for future
  voxel and homogenisation work. It does not currently contain VOLCO or fedoo.
- `gui` serves the browser interface, edits campaign workspaces, and proxies Run
  and artifact requests without doing mechanics calculations.
- `runner` stores immutable Run records and content-addressed artifacts, then
  invokes the pinned experimental-reduction image through the Docker engine.
- `exp-reduction` is the first one-shot scientific stage image. It preserves
  the uploaded CSV bytes and emits result and stage-provenance artifacts.
  `gui` can be shared privately over Tailscale Serve while bound to host loopback.

The GUI workflow imports tensile CSV/TSV files, validates column mappings and
specimen dimensions, and stores a versioned campaign/specimen record with test,
print, sensor, compliance, and input-file hash metadata. It computes a nominal
tensile baseline and a chord modulus per eligible physical specimen, then shows
mean, sample standard deviation, coefficient of variation, and the five-specimen
campaign-readiness check. Desktop saves use revisions to detect conflicting
edits; deleted studies can be restored during the selected retention period.

Solver-independent reference modules now cover tensile and three-point-bend
formulas, classical laminate theory, transversely isotropic stiffness and
failure-index calculations, plus analytical fracture conversions and a
bilinear cohesive envelope. These are calculation references with unit tests;
they are not validated simulation models.

`uv.lock` pins the ordinary project dependencies. The notebook services mount
the working tree for development; formal simulation runs must use baked images
and record their provenance.

The physical tensile/bending-rig data acquisition is intentionally outside the
container. It should write files such as CSV or Parquet; calibration and
simulation run in this environment.

The initial toolpath adapter uses the lightweight `gcodeparser` package. When
timing-aware printer-motion boundary conditions become relevant, add
`pyGCodeDecode` as a separately pinned Git dependency and record its commit in
the simulation provenance; it is not needed to establish the core FEM runtime.

## Quick start: Windows + WSL2

1. Install Docker Desktop with the WSL2 backend, then install the VS Code
   **Dev Containers** extension if you want to use the FEniCSx Dev Container.
2. Clone the repository into the WSL filesystem (for example
   `~/projects/StyrkeAnalyse-FDM`), not under `/mnt/c`.
3. In the WSL terminal, configure a Jupyter token and local user IDs:

   ```bash
   cp .env.example .env
   # Replace the example value with a long random token before starting Jupyter.
   export LOCAL_UID="$(id -u)"
   export LOCAL_GID="$(id -g)"
   ```

   Compose fails with an actionable error if `JUPYTER_TOKEN` is unset. The
   host ports are published only on `127.0.0.1`.

Build and start only the environment you need. Each `up` command runs the
server in the foreground; open its local URL and enter the token from `.env`:

```bash
docker compose build analysis
docker compose up analysis       # http://localhost:8888

docker compose build fenicsx
docker compose up fenicsx        # http://localhost:8889

docker compose build rve
docker compose up rve            # http://localhost:8890
```

Run the solver-independent tests in `analysis` and verify the solver stack in
`fenicsx` with:

```bash
docker compose run --rm analysis pytest -q
docker compose run --rm fenicsx scripts/verify-environment.sh
```

The RVE service currently supplies Python 3.10 plus JupyterLab only. VOLCO,
fedoo, fibergen, and other specialised RVE tools have not been installed.
Jupyter notebooks are a development interface, not formal simulation runs.
For a notebook result to be reproducible, restart its kernel and run every cell
from top to bottom.

```bash
docker compose build analysis
docker compose run --rm analysis python -c "import numpy, scipy; print(numpy.__version__)"
docker compose build rve
docker compose run --rm rve python -c "import sys; assert sys.version_info[:2] == (3, 10)"
docker compose build fenicsx
docker compose run --rm fenicsx scripts/verify-environment.sh
```

## Run the GUI on the home desktop

The browser interface and its saved studies can run on an always-on desktop. Open
it from a phone or laptop on your Tailscale network; the app itself is not
published to the public internet. Formal runs are executed in a network-disabled
stage container. The internal runner needs access to the Docker engine socket to
create that isolated container; Compose does not publish the runner API to the
host.

1. On the desktop, clone or update this repository and configure the existing
   `.env` file as described above. Compose requires `JUPYTER_TOKEN` even when
   starting only the GUI because the other notebook services are part of the
   same Compose project.
2. In the shell where you run Compose, record the checked-out revision on the
   images. These labels are copied into immutable stage provenance:

   ```bash
   export GIT_COMMIT="$(git rev-parse HEAD)"
   if [ -n "$(git status --porcelain)" ]; then export GIT_DIRTY=true; else export GIT_DIRTY=false; fi
   ```

   Build all three images and start the GUI plus runner:

   ```bash
   docker compose build gui runner exp-reduction
   docker compose up -d gui runner
   docker compose ps gui runner
   docker compose logs -f gui runner
   ```

   The GUI listens on host loopback port 8010. Saved studies, Run records, and
   content-addressed artifacts share the persistent `gui_data` Docker volume.
   In the app, use **Save on desktop** to keep studies on the host; **Export
   file** downloads a portable workspace to the device running the browser.
3. Install Tailscale on the desktop and sign it in to your tailnet. Install it
   on your phone and laptop and sign those into the same tailnet. On the
   operating system that runs Tailscale on the desktop, run:

   ```bash
   tailscale serve --bg 8010
   tailscale serve status
   ```

   Serve prints the private HTTPS URL to open on the other devices. Tailscale
   Serve requires HTTPS certificates to be enabled for the tailnet. For a
   Windows + WSL2 setup, run Compose in WSL and run the Tailscale commands in
   Windows, where Docker Desktop publishes port 8010.

The Compose port stays bound to `127.0.0.1`; Tailscale Serve proxies it to
approved devices on your tailnet. Do not change this to `0.0.0.0` and do not use
Tailscale Funnel. Access follows your tailnet's access policy. The notebook
ports 8888–8890 remain local-only and are not part of this GUI route.

Set the desktop not to sleep while plugged in and configure Docker Desktop to
start when you sign in. Compose uses `restart: unless-stopped`, so the GUI
container comes back when Docker starts. If the desktop is asleep or powered
off, remote access is unavailable.

This release runs tensile baseline and replicate reduction workflows and stores
saved workspaces on the desktop. It does not submit or monitor FEM simulation
jobs. The solver verification gate is intentionally red until pinned DOLFINx
and CalculiX images produce recorded convergence, patch-test, analytical
agreement, and cross-solver evidence. FEM-versus-experiment comparison is not
available before then. The GUI itself does not use the GPU, and the existing
Compose configuration does not pass a GPU through to the FEM container.

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

1. Pin and record immutable DOLFINx and CalculiX images; run all four M4
   verification gates and retain their artifacts.
2. Finalize the specimen matrix and collect at least five specimens per
   configuration, including 0°, 90°, upright Z, held-out bend, notched, and DCB
   specimens according to the planned modeling tiers.
3. Implement the isotropic solver and cross-check it against the analytical and
   CLT references before exposing any experiment comparison.
4. Add orthotropic FEM, strength calibration, uncertainty, and a blinded held-out
   bend prediction; only then assess validation.
5. Add J-integral/LEFM and calibrated cohesive behavior after orthotropic
   validation. Pursue phase-field only with mesh-objectivity evidence and the
   required fracture data.
6. Compare G-code-derived material fields against CAD geometry as a controlled
   experiment, not as an assumed improvement.

The printed specimens are the schedule driver, so design the whole matrix and
start that campaign alongside the software work rather than after it.
