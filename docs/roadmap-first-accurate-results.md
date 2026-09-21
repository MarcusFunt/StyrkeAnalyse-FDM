# Roadmap to the first accurate simulation results

This document audits what is actually implemented today, defines what "accurate"
has to mean before the word is usable, and lays out the shortest defensible path
from the current scaffold to a first validated prediction.

It is written against commit `0269782` (branch `main`).

---

## 1. Where the implementation actually stands

### 1.1 What exists

The repository currently contains a **reproducible environment and nothing else**.
That is an honest state for a first commit, and the README says so, but it is worth
being precise about the size of the remaining gap.

| Area | Status |
| --- | --- |
| Container image (DOLFINx + PETSc + MPI, CalculiX, Gmsh) | Implemented |
| `uv.lock` dependency pinning | Implemented |
| Compose + Dev Container for Windows/WSL2 | Implemented |
| `scripts/verify-environment.sh` (import + CLI smoke check) | Implemented |
| Python package `fdm_strength` | Two commands, no physics |
| Toolpath parsing, meshing, material mapping, solvers, calibration, validation | **Not started** |

The whole of `src/fdm_strength` is 25 lines:

- `__init__.py` — a version string.
- `cli.py` — `info`, which prints a banner, and `inspect`, which prints a path and
  a file size. Neither touches the problem domain.

`tests/test_smoke.py` asserts that `__version__ == "0.1.0"` and that the banner
contains the project name. These tests cannot fail for any reason connected to
correctness of a result.

### 1.2 The declared-but-unused surface

Every scientific dependency in `pyproject.toml` is currently unreferenced by the
package. A grep across `src/` finds zero imports of `gcodeparser`, `pynitefea`,
`trimesh`, `meshio`, `polars`, `pyarrow`, `pydantic`, `pyvista` or `scipy`.
They appear only inside `scripts/verify-environment.sh`, which imports them to
prove the image built.

This is fine as intent-signalling, but it means the dependency list is a plan,
not a description. Expect at least one of these choices to be revisited under
contact with the actual problem — `pynitefea` in particular is a frame/truss
solver and will not carry a continuum specimen model; it is useful only for the
analytical/beam-level cross-check in M1.

### 1.3 Defects to fix before they cost you a dataset

These are small, but each one silently corrupts results or reproducibility later.

1. **`DOLFINX_IMAGE` defaults to the moving `stable` tag.**
   `compose.yaml` and `docker/Dockerfile` both default to
   `ghcr.io/fenics/dolfinx/dolfinx:stable`. Two rebuilds a month apart are two
   different solvers. The README states the rule ("replace with an exact
   release/digest before generating results") but nothing enforces or records it.
   Until this is pinned by digest, **no number produced in this container is
   reproducible**, which makes it unusable for the report regardless of accuracy.

2. **No unit convention is declared anywhere.**
   This is the single most common cause of wrong FEM output. `mm / N / MPa /
   tonne` and strict SI (`m / N / Pa / kg`) are both defensible; mixing them
   silently produces results wrong by 10^6 with no error. Decide now, write it
   down, and enforce it in code before the first solver call.

3. **`.gitignore` blocks your own reference data.**
   Line 20 (`*.csv`) and line 21 (`*.parquet`) are global patterns.
   `git check-ignore` confirms that `data/reference/coupons.csv` is ignored.
   Ignoring bulk output is right; ignoring small committed golden/reference
   datasets is not. Add negations, e.g.:

   ```gitignore
   !data/reference/**/*.csv
   !tests/data/**/*.csv
   ```

   Also note `*.msh` is ignored, so no small mesh can be committed as a
   regression fixture.

4. **`inspect` records nothing.** Provenance has to start at the moment an input
   file enters the environment. The command should emit a SHA-256, not a byte
   count — it is a two-line change now and an archaeology exercise later.

5. **The test suite provides no protection.** Tautological assertions on a
   version constant will stay green through any physics error. See §6.

---

## 2. What "accurate" has to mean

A simulation result is not accurate or inaccurate in isolation; it is accurate
*relative to a measurement, within a stated tolerance, on a quantity you named in
advance*. Three things must be fixed before the word is usable.

### 2.1 Separate verification from validation

These fail for different reasons and are fixed by different work.

- **Verification** — *are the equations solved correctly?* Compared against exact
  solutions, convergence rates and an independent solver. No experimental data
  involved. A verification failure is a bug.
- **Validation** — *are they the correct equations for this material?* Compared
  against measurements, with uncertainty on both sides. A validation failure is a
  modelling or calibration error.

Running validation before verification passes is the classic failure mode: you
tune material constants to absorb a discretisation error, get agreement on the
calibration geometry, and then the model fails on anything else. **Do not
compare against experiment until §4 M3's verification gate is green.**

### 2.2 Name the quantities of interest up front

Commit to these before the first comparison, so the target cannot move:

| QoI | Where it comes from | Proposed target |
| --- | --- | --- |
| Elastic modulus (loading direction) | Chord slope, strain 0.0005–0.0025 | within ±5 % of coupon mean |
| Stiffness of the structural test (F/δ) | Linear region slope | within ±10 % |
| Peak force at failure | Max of the F–δ curve | within ±15 % (isotropic), ±10 % (orthotropic) |
| Failure location | Visual / photographic | correct region, qualitative |

The peak-force targets are deliberately looser than the stiffness targets.
Stiffness is a volume average and predicts well; strength is governed by the
worst defect in the specimen and predicts badly. A model that hits peak force to
±5 % on FDM parts is more likely over-fitted than good.

### 2.3 You cannot be more accurate than your scatter

FDM coupons routinely show a coefficient of variation of 5–15 % in strength
between nominally identical prints. A ±10 % accuracy claim against a single
specimen is meaningless. Therefore:

- **n ≥ 5** specimens per configuration, always.
- Report mean ± standard deviation, and report the CoV alongside every target.
- The acceptance criterion is *the prediction falls within the experimental
  scatter band*, not *the prediction matches specimen #3*.

If measured CoV exceeds ~15 %, stop and fix the printing process before doing any
more modelling work. No constitutive model recovers from an uncontrolled process.

---

## 3. The FDM-specific traps

These are the reasons an otherwise correct FEM gives wrong answers on printed
parts. Each one needs an explicit decision recorded in the material profile.

1. **Interlayer strength is the governing weakness.** Z-direction (upright print)
   tensile strength is commonly 30–60 % of in-plane strength, and it fails
   brittle. A model calibrated only on flat-printed XY coupons will overpredict
   any part loaded across layers. **A Z-oriented coupon is not optional.**

2. **Voids: decide where porosity lives, once.** Inter-bead voids can be
   represented in the *geometry* (reduced effective cross-section) or in the
   *stiffness* (knocked-down moduli), never both. Double-counting is easy and
   produces a model that is ~15 % too compliant for no visible reason. The
   recommendation: keep nominal CAD geometry, put all porosity into the
   calibrated moduli, and always divide measured force by the **measured**
   specimen cross-section when reducing experimental data.

3. **Machine compliance and grip slip.** Crosshead displacement includes load
   frame stretch and specimen slip in the grips. Using it as specimen strain
   underestimates modulus by 10–30 % — which then propagates into every
   subsequent "validated" prediction. Use a clip-on extensometer or DIC; if
   neither is available, characterise the frame compliance with a stiff steel
   dummy and subtract it, and record that you did.

4. **The slicer profile is part of the material.** Layer height, extrusion width,
   nozzle and bed temperature, print speed, cooling, and infill pattern all move
   the moduli. Any change to the profile invalidates the calibration. Hash the
   profile file and store the hash in the material profile.

5. **Raster angle must be recorded per specimen.** Without it the calibration
   dataset is unusable, and it cannot be recovered after the fact.

6. **Seams, first layer and brim** are stress concentrations that the homogenised
   model does not know about. If failures cluster at the seam, that is a signal
   the model cannot yet be expected to place failure correctly.

7. **Environment.** PLA creeps at modest temperature and anneals; PA absorbs
   moisture and softens dramatically. Record ambient temperature and humidity,
   and the time between printing and testing.

---

## 4. The critical path

Milestones are ordered by dependency. Each has an explicit gate — do not start
the next milestone until the gate is green.

### M0 — Foundations: units, schema, provenance *(no solver)*

**Build**

- `fdm_strength/units.py` — a single declared convention plus named constants.
  Recommendation: **mm, N, MPa, tonne** (so density is in t/mm³). It keeps
  specimen dimensions and stresses in human-readable magnitudes and matches
  CalculiX practice. Whatever you choose, make conversions explicit at the
  boundaries and never inside the solver layer.
- `fdm_strength/schema.py` — pydantic models for `Specimen`, `MaterialProfile`,
  `PrintProfile`, `TestRun`, `ToolpathModel`, `SimulationResult`. These are the
  contract the rest of the project is written against; getting them right is
  cheap now and expensive in M4.
- `fdm_strength/provenance.py` — a record capturing, at minimum:
  git commit and dirty flag; container image **digest**; hash of `uv.lock`;
  SHA-256 of every input (STL, G-code, slicer profile, experimental data file);
  mesh parameters and mesh hash; material profile id and hash; solver name and
  version; boundary-condition set id; timestamp; hash of the result file.
- Pin `DOLFINX_IMAGE` to a digest in `.env` and record it.
- Fix the `.gitignore` negations and make `inspect` emit a SHA-256.

**Gate**
`fdm-strength provenance --run <dir>` emits a complete record; schema round-trip
tests pass; a deliberately modified input changes the recorded hash.

### M1 — Analytical baselines *(the oracle for everything after)*

**Build** `fdm_strength/analytical.py`:

- Uniaxial tension: `σ = F/A`, `ε = δ/L₀`, chord modulus over ε ∈ [0.0005, 0.0025]
  (ISO 527-1), with an explicit machine-compliance correction term.
- Three-point bend (ISO 178, span-to-depth 16:1):
  `σ_f = 3FL / (2bh²)`, `ε_f = 6δh / L²`, `E_f = L³m / (4bh³)` where `m` is the
  force–deflection slope.
- Optionally the `pynitefea` beam cross-check for the bend case.

**Gate**
Unit tests against hand-computed values for a known geometry, to 1e-12. These
functions become the reference the FEM is verified against — they must be
trustworthy before anything else leans on them.

### M2 — Experimental campaign and calibration coupons

**This is the long pole. Start printing while M0/M1 software work is in flight.**

You cannot validate a simulation before you have material data measured on *your*
printer with *your* profile. Published PLA moduli span roughly 2.5–3.9 GPa; any
of them is a guess for your machine, and a guessed modulus makes a "validated"
model meaningless.

**Coupon matrix** (ISO 527-2 Type 1A tensile, n ≥ 5 each):

| Coupon | Raster | Yields |
| --- | --- | --- |
| A | 0° (aligned with load) | `E1`, `ν12`, `X_t` |
| B | 90° (transverse) | `E2`, `Y_t` |
| C | ±45° (ASTM D3518) | `G12 = σx / (2(εx − εy))`, `S` |
| D | upright / Z-oriented | interlayer `E3`, `Z_t` — **do not skip** |

Also print a small batch of ISO 178 bend bars (80 × 10 × 4 mm, 64 mm span) at a
raster angle **not** in the calibration set — these are held back for M4.

**Build** `fdm_strength/experiment.py`: load raw rig output (CSV/Parquet) into
the `TestRun` schema, apply compliance correction, extract chord modulus, peak
force, and failure strain; emit per-configuration mean/SD/CoV.

**Gate**
CoV ≤ 15 % per configuration; compliance correction applied and documented;
reduced data written to a hashed Parquet with a provenance record attached.

### M3 — Isotropic DOLFINx baseline *(first point where "accurate" is meaningful)*

**Build**

- `fdm_strength/mesh.py` — Gmsh parametric specimen geometry (do not start from
  STL; a parametric bar removes an entire class of geometry ambiguity) with
  controllable characteristic length.
- `fdm_strength/solvers/dolfinx_linear.py` — small-strain linear elasticity,
  isotropic, with boundary conditions that actually represent the rig: model the
  grip as a clamped face over the true grip length, not a point constraint, and
  apply load as a traction over the gripped area.

**Use P2 (quadratic) tetrahedra for the bending model.** Linear tets are
excessively stiff in bending and will make a three-point-bend prediction wrong by
a large factor while converging smoothly and looking entirely healthy. This is
the highest-probability silent error in the whole plan.

**Verification gate — all four must pass, before any experimental comparison:**

1. **Manufactured solution / convergence study.** L2 displacement error converges
   at O(h²) for P1 and O(h³) for P2 under uniform refinement. A wrong rate means
   a bug in the weak form, BCs or quadrature.
2. **Uniform stress patch test.** A prismatic bar under end traction reproduces
   `σ = F/A` to ~1e-12 relative, everywhere.
3. **Against M1 analytics.** Tensile stiffness within 0.1 %; three-point-bend
   stiffness within 1 % of Euler–Bernoulli with shear correction, on a converged
   mesh.
4. **CalculiX cross-check.** Export the same mesh (C3D10), same BCs, same
   isotropic constants; peak displacement agrees within 0.5 %. This catches
   errors that both of your own implementations would share.

**Validation** Only now: compare to the M2 tensile and bend data using
coupon-measured isotropic constants. Expect stiffness inside ±10 %, and expect
strength to be *over*predicted — that gap is the physical motivation for M4.

### M4 — Homogenised orthotropic model *(the first genuinely new result)*

**Build**

- Constitutive model: full orthotropy needs 9 constants, which you do not have.
  Use the standard transversely-isotropic reduction about the raster direction —
  `E2 = E3`, `G12 = G13`, `ν12 = ν13`, `G23 = E2 / (2(1 + ν23))` — giving five
  independent constants `E1, E2, ν12, ν23, G12`, all measured in M2.
- A per-element local material frame aligned with the raster direction.
- Failure post-processing: rotate stress into the material frame and evaluate a
  **maximum-stress criterion first** (`σ1/X`, `σ2/Y`, `τ12/S`). It is less
  smooth than Tsai-Hill but tells you *which* mode is critical, which is what you
  need while debugging. Add Tsai-Hill as a refinement once max-stress behaves.

**Gate — and this is the one that matters:**

Reproducing coupons A–D is a *consistency check*, not validation — those coupons
set the constants, so agreement is arithmetic, not evidence. The real gate is a
**blind prediction**: predict stiffness, peak force and failure location for the
held-back bend bars from M2 *and write the prediction down before unblinding the
measurements*.

**A blind prediction landing inside the experimental scatter band is your first
accurate simulation result.** Everything before it is infrastructure, and
everything after it is refinement.

### M5 — G-code-informed local fields

Only after M4 validates. `gcodeparser` → normalised `ToolpathModel` → per-element
raster orientation and local porosity → spatially varying stiffness tensor.
Validate against a geometry where the toolpath genuinely varies through the part
(a curved or notched specimen), because on a straight bar M5 degenerates to M4
and cannot show improvement. Per the README, defer `pyGCodeDecode` until
timing-aware boundary conditions are actually needed.

---

## 5. Sequencing

The software milestones are mostly serial; the physical campaign is not, and it
is the schedule driver.

```text
M0 schema/units/provenance  ──┐
M1 analytical baselines     ──┼──► M3 isotropic FEM + verification ──► M4 orthotropic ──► M5 G-code
                              │         ▲                                   ▲
M2 print + test coupons ──────┘─────────┴───────────────────────────────────┘
   (start immediately — printing and testing dominates elapsed time)
```

Start M2 printing on day one. M0 and M1 are a few days of focused work; the
coupon campaign with n ≥ 5 across four configurations plus bend bars is weeks
including reprints, and any process problem discovered during testing sends you
back to the start of it.

---

## 6. Test strategy

Replace the current tautological suite with three tiers, separated by pytest
markers so the fast tier stays usable:

- **`unit`** (milliseconds, no solver) — schema round-trips, unit conversions,
  analytical formulas against hand-computed values, experimental-reduction logic
  against synthetic curves with known slope.
- **`verification`** (marked, needs DOLFINx/CalculiX) — convergence rates, patch
  test, analytical agreement, cross-solver agreement. These are the tests that
  would actually have caught a P1-tet bending error.
- **`validation`** (marked, needs data) — comparison against committed reduced
  coupon data with the tolerance bands from §2.2. Skipped when data is absent so
  the suite stays green on a clean checkout.

Extend `scripts/verify-environment.sh` to run `unit` always and `verification`
when the solver stack is present. Add CI that runs at least the `unit` tier.

---

## 7. Definition of done for the first accurate result

All of the following, together:

- [ ] Container pinned by digest; a provenance record exists for the run and its
      hashes resolve.
- [ ] All four M3 verification gates pass and are recorded in the run artefacts.
- [ ] Material constants come from measured coupons on the same printer and
      profile, with CoV ≤ 15 % and n ≥ 5.
- [ ] A prediction was written down **before** the comparison data was unblinded.
- [ ] The predicted stiffness and peak force fall inside the experimental scatter
      band, and the predicted failure region matches observation.
- [ ] Re-running from the recorded provenance on a clean checkout reproduces the
      numbers.

Anything short of this is a preliminary number, and should be labelled as one in
the SOP.

---

## 8. Immediate next commits

Ordered, each small enough to land independently:

1. Pin `DOLFINX_IMAGE` to a digest; record it in `.env.example` and the README.
2. Fix the `.gitignore` negations for `data/reference/` and `tests/data/`.
3. Add `units.py` with the declared convention and conversion helpers.
4. Add `schema.py` with `Specimen`, `MaterialProfile`, `PrintProfile`, `TestRun`.
5. Add `provenance.py` plus `fdm-strength provenance`; make `inspect` hash inputs.
6. Add pytest markers and drop the tautological version assertion.
7. Add `analytical.py` with the tension and three-point-bend reductions + tests.
8. Add `mesh.py` with a parametric ISO 527-2 1A bar in Gmsh.
9. Add the DOLFINx isotropic solver and the convergence/patch-test verification.
10. Add the CalculiX export and the cross-solver comparison test.

In parallel, starting now: print and test the M2 coupon matrix.
