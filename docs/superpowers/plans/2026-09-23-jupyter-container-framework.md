# Jupyter Container Framework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three isolated, local-only Jupyter environments for baseline analysis, FEniCSx modelling, and Python-3.10 RVE work.

**Architecture:** Compose owns the three service boundaries. The existing DOLFINx image becomes `fenicsx`; new focused Dockerfiles supply `analysis` and `rve`. All services mount the repository only for interactive development, while formal runs remain a separate baked-image workflow defined by the existing execution-environments document.

**Tech Stack:** Docker Compose, JupyterLab, Python 3.10/3.12, existing DOLFINx/PETSc/MPI/CalculiX image, Bash.

**Spec:** `docs/superpowers/specs/2026-09-23-jupyter-container-framework-design.md`

## Global Constraints

- Implement exactly `analysis`, `fenicsx`, and `rve`; do not add DIC, legacy-FEniCS, or fracture services.
- Bind Jupyter to `127.0.0.1` and require a configured token.
- Keep notebooks thin: executable modelling logic lives under `src/fdm_strength/`.
- Do not claim VOLCO, fedoo, fibergen, or PhaseFieldX are installed.
- Keep the existing frozen project dependency set unchanged unless a generated lockfile is committed in the same change.
- Development source mounts are not formal reproducible simulation runs.

## Review Focus

- A missing `JUPYTER_TOKEN` must fail fast with an actionable message rather than start an unauthenticated server.
- The three Jupyter host ports must remain distinct and bind only to loopback.
- `fenicsx` must still expose `ccx`, `gmsh`, MPI, DOLFINx, and the existing verification script.
- `analysis` and `rve` must accept the mounted project source without writing root-owned files.
- The example notebook must run after a kernel restart without relying on prior cell state.

---

### Task 1: Compose service contract and static verifier

**Files:**
- Modify: `compose.yaml`
- Create: `scripts/verify-compose-config.sh`
- Modify: `.gitignore`
- Test: `scripts/verify-compose-config.sh`

**Interfaces:**
- Consumes: Docker Compose v2 and `.env`.
- Produces: services `analysis`, `fenicsx`, and `rve`; a shell verifier that exits zero only if their rendered configuration meets the spec.

- [ ] **Step 1: Write the failing Compose-contract test**

Create `scripts/verify-compose-config.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

config=$(docker compose config)
for service in analysis fenicsx rve; do
  grep -q "^  ${service}:" <<<"$config"
done
grep -q '127.0.0.1:8888:8888' <<<"$config"
grep -q '127.0.0.1:8889:8888' <<<"$config"
grep -q '127.0.0.1:8890:8888' <<<"$config"
grep -q 'JUPYTER_TOKEN' <<<"$config"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `bash scripts/verify-compose-config.sh`

Expected: FAIL because `analysis` and `rve` do not exist and the current service is named `dev`.

- [ ] **Step 3: Implement the three-service Compose configuration**

Replace the current `dev` service with:

```yaml
analysis:
  build:
    context: .
    dockerfile: docker/analysis.Dockerfile
  ports: ["127.0.0.1:8888:8888"]
fenicsx:
  build:
    context: .
    dockerfile: docker/Dockerfile
  ports: ["127.0.0.1:8889:8888"]
rve:
  build:
    context: .
    dockerfile: docker/rve.Dockerfile
  ports: ["127.0.0.1:8890:8888"]
```

For every service, mount the repository at `/workspaces/styrkeanalyse-fdm`, set a non-root UID/GID, and use a Jupyter command that expands `${JUPYTER_TOKEN:?set JUPYTER_TOKEN in .env}` before launching `jupyter lab --ip=127.0.0.1 --port=8888 --no-browser`. Add `.env` to `.gitignore` and create `.env.example` containing `JUPYTER_TOKEN=replace-with-a-long-random-token`.

- [ ] **Step 4: Run static verification**

Run: `bash scripts/verify-compose-config.sh`

Expected: PASS when `JUPYTER_TOKEN=development-only-token` is supplied in the environment.

- [ ] **Step 5: Commit**

```bash
git add compose.yaml .gitignore .env.example scripts/verify-compose-config.sh
git commit -m "feat: add isolated notebook Compose services"
```

### Task 2: Analysis and RVE image boundaries

**Files:**
- Create: `docker/analysis.Dockerfile`
- Create: `docker/rve.Dockerfile`
- Create: `docker/jupyter-requirements.txt`
- Modify: `docker/Dockerfile`
- Test: `scripts/verify-environment.sh`

**Interfaces:**
- Consumes: `pyproject.toml`, `uv.lock`, `src/`, and the Compose UID/GID build arguments.
- Produces: `analysis` with normal scientific Python plus Jupyter; `rve` with Python 3.10 plus Jupyter; `fenicsx` with the existing solver stack plus Jupyter.

- [ ] **Step 1: Write image smoke commands before modifying Dockerfiles**

Record these commands in the README Quick Start draft:

```bash
docker compose build analysis
docker compose run --rm analysis python -c "import numpy, scipy; print(numpy.__version__)"
docker compose build rve
docker compose run --rm rve python -c "import sys; assert sys.version_info[:2] == (3, 10)"
docker compose build fenicsx
docker compose run --rm fenicsx scripts/verify-environment.sh
```

- [ ] **Step 2: Verify the two new image commands fail**

Run the first `docker compose build analysis` and `docker compose build rve` commands.

Expected: FAIL because their Dockerfiles do not exist.

- [ ] **Step 3: Implement exact image responsibilities**

Create `docker/jupyter-requirements.txt` with these exact direct requirements:

```text
jupyterlab==4.4.10
ipykernel==6.30.1
matplotlib==3.10.7
pytest==8.4.2
numpy==2.2.6
scipy==1.15.3
```

Create `docker/analysis.Dockerfile` from `python:3.12-slim-bookworm` and `docker/rve.Dockerfile` from `python:3.10-slim-bookworm`. Both must create the `fdm` user from `USER_UID` and `USER_GID`, copy and install `docker/jupyter-requirements.txt`, use `/workspaces/styrkeanalyse-fdm` as their working directory, and contain no FEM, VOLCO, or legacy FEniCS install.

Update `docker/Dockerfile` to copy the same requirements file and install it into the existing `/opt/venv` after its frozen project sync. Keep its DOLFINx and CalculiX verification imports unchanged.

- [ ] **Step 4: Build and run image smoke commands**

Run the three commands from Step 1. Also run:

```bash
docker compose run --rm analysis jupyter lab --version
docker compose run --rm rve jupyter lab --version
docker compose run --rm fenicsx jupyter lab --version
```

Expected: every command exits zero; only `fenicsx` runs `scripts/verify-environment.sh`.

- [ ] **Step 5: Commit**

```bash
git add docker/analysis.Dockerfile docker/rve.Dockerfile docker/jupyter-requirements.txt docker/Dockerfile
git commit -m "feat: add analysis and RVE notebook images"
```

### Task 3: Restartable teaching notebook and documentation

**Files:**
- Create: `notebooks/01_baseline_tensile_stress.ipynb`
- Create: `src/fdm_strength/baseline.py`
- Create: `tests/test_baseline.py`
- Modify: `README.md`
- Modify: `docs/execution-environments.md`
- Test: `tests/test_baseline.py`

**Interfaces:**
- Consumes: force in newtons and cross-sectional area in square millimetres.
- Produces: `nominal_tensile_stress_mpa(force_newton: float, area_mm2: float) -> float` and a notebook that calls it.

- [ ] **Step 1: Write the failing unit tests**

Create `tests/test_baseline.py`:

```python
import pytest
from fdm_strength.baseline import nominal_tensile_stress_mpa

def test_nominal_tensile_stress_uses_newton_per_square_millimetre():
    assert nominal_tensile_stress_mpa(850.0, 40.0) == 21.25

@pytest.mark.parametrize("area_mm2", [0.0, -1.0])
def test_nominal_tensile_stress_rejects_non_positive_area(area_mm2):
    with pytest.raises(ValueError, match="area_mm2 must be positive"):
        nominal_tensile_stress_mpa(100.0, area_mm2)
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `docker compose run --rm analysis pytest tests/test_baseline.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'fdm_strength.baseline'`.

- [ ] **Step 3: Implement the reusable calculation**

Create `src/fdm_strength/baseline.py`:

```python
def nominal_tensile_stress_mpa(force_newton: float, area_mm2: float) -> float:
    if area_mm2 <= 0:
        raise ValueError("area_mm2 must be positive")
    return force_newton / area_mm2
```

Create the notebook with Markdown explaining that `1 N/mm² = 1 MPa`, one code cell importing the function, and one plotting cell. Its first code cell must add the mounted `src` directory to `sys.path` so it runs in the clean analysis image.

- [ ] **Step 4: Run the focused and whole test suite**

Run:

```bash
docker compose run --rm analysis pytest tests/test_baseline.py -q
docker compose run --rm analysis pytest -q
```

Expected: PASS.

- [ ] **Step 5: Document the exact local workflow**

Update the README to explain the three services, copy-paste `.env.example` to `.env`, and give the exact commands to start each notebook server. State explicitly that `rve` currently provides Python 3.10 plus Jupyter only and does not yet contain VOLCO/fedoo. Update `docs/execution-environments.md` to mark these three as implemented development environments and the other image families as deferred.

- [ ] **Step 6: Commit**

```bash
git add notebooks/01_baseline_tensile_stress.ipynb src/fdm_strength/baseline.py tests/test_baseline.py README.md docs/execution-environments.md
git commit -m "docs: add reproducible notebook workflow"
```

### Task 4: Branch-level verification and pull request

**Files:**
- Modify: `README.md` only if a verification result exposes a documentation mismatch.
- Test: `scripts/verify-compose-config.sh`, `tests/`, and each image smoke command.

**Interfaces:**
- Consumes: the three images and example notebook from Tasks 1–3.
- Produces: a reviewable pull request with the exact verification results.

- [ ] **Step 1: Run source-independent configuration verification**

Run: `JUPYTER_TOKEN=development-only-token bash scripts/verify-compose-config.sh`

Expected: PASS.

- [ ] **Step 2: Run all requested image and unit verification**

Run:

```bash
docker compose build analysis rve fenicsx
docker compose run --rm analysis pytest -q
docker compose run --rm rve python -c "import sys; assert sys.version_info[:2] == (3, 10)"
docker compose run --rm fenicsx scripts/verify-environment.sh
```

Expected: all exit zero.

- [ ] **Step 3: Verify notebook restartability**

Run:

```bash
docker compose run --rm analysis jupyter nbconvert \
  --to notebook --execute --inplace \
  --ExecutePreprocessor.timeout=60 \
  notebooks/01_baseline_tensile_stress.ipynb
```

Expected: PASS, with the notebook executing from a new kernel.

- [ ] **Step 4: Commit the final verification-safe state**

```bash
git status --short
git add README.md docs/ notebooks/ src/ tests/ compose.yaml docker/ scripts/ .env.example .gitignore
git commit -m "test: verify Jupyter container framework"
```

Expected: the working tree is clean after the commit.

- [ ] **Step 5: Open a pull request**

Open a PR from `codex/jupyter-container-framework` to `main` titled `Add isolated Jupyter development environments`. Its description must state the three services, explicitly state that RVE tools are intentionally not installed yet, and list the completed verification commands.
