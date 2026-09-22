# Roadmap to the first accurate simulation results

This document audits what is actually implemented today, defines what "accurate"
has to mean before the word is usable, and lays out the shortest defensible path
from the current scaffold to a first validated prediction.

It is written against commit `0269782` (branch `main`) and against the project's
source review (`Kilder – alle kilder med metoder`, 86 entries). Bracketed numbers
such as [17] refer to that list; §10 maps each milestone back to its sources.

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

The source review reaches the same conclusion about one of them independently:
PyNite is a frame/truss solver and is "for groft til realistisk bead-level
fracture" [57]. It is useful only as the classical beam cross-check in M1, and
should not be planned into any later milestone.

### 1.3 Defects to fix before they cost you a dataset

These are small, but each one silently corrupts results or reproducibility later.

1. **`DOLFINX_IMAGE` defaults to the moving `stable` tag.**
   `compose.yaml` and `docker/Dockerfile` both default to
   `ghcr.io/fenics/dolfinx/dolfinx:stable`. Two rebuilds a month apart are two
   different solvers. The README states the rule ("replace with an exact
   release/digest before generating results") but nothing enforces or records it.
   Until this is pinned by digest, **no number produced in this container is
   reproducible**, which makes it unusable for the SOP regardless of accuracy.

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
   version constant will stay green through any physics error. See §7.

---

## 2. What the source base settles, and what it leaves to you

The 86-entry review is not background reading; it constrains the plan. Five
things in it change what should be built, and in what order.

### 2.1 The question is fracture, not stiffness

The bulk of the core sources target crack initiation, crack path and peak load —
XFEM [9][20][27], phase-field [18][66][67], cohesive zone [38][79], J-integral
[62][63], mixed-mode [19], interlayer DCB [65]. A model that predicts stiffness
well and says nothing about where the part breaks does not answer the SOP's
question. The milestone ladder below therefore ends in a fracture tier, and the
coupon campaign has to produce fracture parameters, not just elastic constants.

### 2.2 The methods table already fixes the ladder

The review's own overview assigns each method a role: classical statics as
baseline; orthotropic elasticity + CLT as "hovedmodel nr. 2"; Tsai–Wu as "god
første anisotrope brudmodel"; CZM "meget relevant til interlayer brud"; XFEM
"god avanceret sammenligning"; phase-field "bedst som avanceret benchmark";
RVE/homogenisation as the intermediate step; G-code/voxel reconstruction as "et
af de mest interessante projektspecifikke spor". This roadmap follows that
ordering rather than inventing a different one.

### 2.3 CLT is a cheap, strong baseline that the current plan omitted

Classical laminate theory applied to raster layers is reported at roughly **1.5 %
mean relative error for tensile modulus** [42], with the same approach used in
[1][3][64]. That is a better stiffness baseline than an isotropic 3D FEM, it
needs no mesh, and it runs in milliseconds. It belongs between the analytical
statics and the 3D solver, not after them — see M2.

### 2.4 Composite strength theory has documented limits here

Tsai–Wu is the standard first anisotropic criterion [76] and is used in FDM work
[1][29], but the review deliberately includes counter-evidence: composite
strength theory has documented limitations for ultimate strength of layered 3D
printing polymers [39], and mechanism-based damage work shows where simple
criteria stop being sufficient [29]. Plan Tsai–Wu as a baseline whose failure is
itself a result, not as the target model. The honest framing for the SOP is:
*how far does a failure index get you, and where does it break down?*

### 2.5 Geometric detail is a hypothesis, not an improvement

The most important methodological warning in the review is [37]: more geometric
detail does not automatically give better prediction, and the methods table
repeats it — "geometrisk detalje hjælper kun hvis materialemodellen også er
god". [70] supports the other side, showing bead shape and inter-bead voids
matter at part scale. **This is the project's actual research question**, so M6
must be run as a controlled comparison (same specimen, same material model,
CAD geometry vs G-code-derived fields) and not as an assumed upgrade.

---

## 3. What "accurate" has to mean

A simulation result is not accurate or inaccurate in isolation; it is accurate
*relative to a measurement, within a stated tolerance, on a quantity you named in
advance*. Three things must be fixed before the word is usable.

### 3.1 Separate verification from validation

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
compare against experiment until §5 M4's verification gate is green.**

### 3.2 Name the quantities of interest up front

Commit to these before the first comparison, so the target cannot move:

| QoI | Where it comes from | Proposed target |
| --- | --- | --- |
| Elastic modulus (loading direction) | Chord slope, strain 0.0005–0.0025 | within ±5 % of coupon mean |
| Stiffness of the structural test (F/δ) | Linear region slope | within ±10 % |
| Peak force at failure | Max of the F–δ curve | within ±15 % (isotropic), ±10 % (orthotropic) |
| Failure location / crack path | Photograph, or DIC strain field | correct region and orientation |
| Full-field strain (if DIC is available) | DIC vs FE strain field | qualitative agreement, RMS reported |

The peak-force targets are deliberately looser than the stiffness targets.
Stiffness is a volume average and predicts well; strength is governed by the
worst defect in the specimen and predicts badly. A model that hits peak force to
±5 % on FDM parts is more likely over-fitted than good.

Crack path is a first-class QoI because the fracture sources treat it as one
[9][18][62] — a model can get peak load right and the crack in the wrong place,
and that must be reported rather than hidden.

### 3.3 You cannot be more accurate than your scatter

FDM coupons routinely show a coefficient of variation of 5–15 % in strength
between nominally identical prints. A ±10 % accuracy claim against a single
specimen is meaningless. Therefore:

- **n ≥ 5** specimens per configuration, always.
- Report mean ± standard deviation, and the CoV alongside every target.
- The acceptance criterion is *the prediction falls within the experimental
  scatter band*, not *the prediction matches specimen #3*.

If measured CoV exceeds ~15 %, stop and fix the printing process before doing any
more modelling work. No constitutive model recovers from an uncontrolled process.

[36] is the method reference for doing this properly: parameter identification
with explicit uncertainty quantification and an independent validation step.
Identified constants should carry an uncertainty, and that uncertainty should be
propagated into the prediction band rather than quoted as a single number.

---

## 4. The FDM-specific traps

These are the reasons an otherwise correct FEM gives wrong answers on printed
parts. Each one needs an explicit decision recorded in the material profile.

1. **Interlayer strength is the governing weakness.** Z-direction (upright print)
   tensile strength is commonly 30–60 % of in-plane strength, and it fails
   brittle. A model calibrated only on flat-printed XY coupons will overpredict
   any part loaded across layers. **A Z-oriented coupon is not optional**, and
   [65] shows the interlayer interface deserves its own fracture test (DCB),
   not just a strength number.

2. **Voids: decide where porosity lives, once.** Inter-bead voids can be
   represented in the *geometry* (reduced effective cross-section) or in the
   *stiffness* (knocked-down moduli), never both. Double-counting is easy and
   produces a model that is ~15 % too compliant for no visible reason. The
   recommendation: keep nominal CAD geometry, put all porosity into the
   calibrated moduli, and always divide measured force by the **measured**
   specimen cross-section when reducing experimental data. [70] is the reference
   for when this assumption starts to cost you accuracy.

3. **Machine compliance and grip slip.** Crosshead displacement includes load
   frame stretch and specimen slip in the grips. Using it as specimen strain
   underestimates modulus by 10–30 % — which then propagates into every
   subsequent "validated" prediction. Use a clip-on extensometer or DIC
   [82][31][63]; if neither is available, characterise the frame compliance with
   a stiff steel dummy and subtract it, and record that you did. If the rig is
   self-built [53], this correction is mandatory, not optional.

4. **The slicer profile is part of the material.** Layer height, extrusion width,
   nozzle and bed temperature, print speed, cooling, and infill pattern all move
   the moduli [13]. Any change to the profile invalidates the calibration. Hash
   the profile file and store the hash in the material profile.

5. **Raster angle must be recorded per specimen**, and ideally controlled
   directly rather than inferred from the slicer. [16] and SciSlice [61] exist
   precisely for this; OrcaSlicer/PrusaSlicer [59][60] are acceptable if the
   profile and version are pinned and archived.

6. **Seams, first layer and brim** are stress concentrations the homogenised
   model does not know about. If failures cluster at the seam, that is a signal
   the model cannot yet be expected to place failure correctly.

7. **Environment.** PLA creeps at modest temperature and anneals. Record ambient
   temperature and humidity, and the time between printing and testing.

8. **Manufacturer data is a sanity check, not calibration.** The PolyLite PLA
   datasheet [51] has XY and Z tensile numbers and is useful to confirm your own
   values are in the right range. It is a producer source, not independent
   evidence, and cannot substitute for coupons printed on your machine.

---

## 5. The critical path

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
  cheap now and expensive in M5.
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
  (ISO 527 [50] / ASTM D638 [46]), with an explicit machine-compliance
  correction term.
- Three-point bend (ISO 178 [49] / ASTM D790 [48], span-to-depth 16:1):
  `σ_f = 3FL / (2bh²)`, `ε_f = 6δh / L²`, `E_f = L³m / (4bh³)` where `m` is the
  force–deflection slope.
- Optionally the `pynitefea` beam cross-check for the bend case — its only role
  in the project [57].

**Gate**
Unit tests against hand-computed values for a known geometry, to 1e-12. These
functions become the reference the FEM is verified against — they must be
trustworthy before anything else leans on them.

### M2 — Classical laminate theory *(high value per hour)*

**Build** `fdm_strength/clt.py`: each raster layer as an orthotropic lamina,
stacked into an ABD matrix, giving laminate in-plane and flexural moduli for an
arbitrary raster sequence.

This is the cheapest model in the whole ladder that captures anisotropy, it is
the review's "hovedmodel nr. 2", and [42] reports ~1.5 % mean relative error on
tensile modulus. It also gives you a second independent stiffness prediction to
check the 3D FEM against before any experiment is involved.

**Gate**
A unidirectional laminate reproduces the input lamina constants exactly; a
symmetric cross-ply reproduces hand-computed ABD terms; CLT and the M4 3D FEM
agree on in-plane laminate modulus to within 1 % for the same constants.

### M3 — Experimental campaign *(the schedule driver — start immediately)*

You cannot validate a simulation before you have material data measured on *your*
printer with *your* profile. Published PLA moduli span roughly 2.5–3.9 GPa; any
of them is a guess for your machine, and a guessed modulus makes a "validated"
model meaningless.

**Design the whole matrix before printing anything, and print it in one batch
with spares.** Process drift between batches [13] makes specimens from different
sessions non-comparable, and a reprint costs weeks.

**Which test you need is decided by how far up the ladder you intend to go:**

| Specimen | Standard | Raster / orientation | Yields | Needed for |
| --- | --- | --- | --- | --- |
| A — tensile | ISO 527-2 [50] / D638 [46] | 0° | `E1`, `ν12`, `X_t` | CLT, orthotropic FE |
| B — tensile | ISO 527-2 / D638 | 90° | `E2`, `Y_t` | CLT, orthotropic FE |
| C — tensile | D3518-style ±45° | ±45° | `G12`, `S` | CLT, orthotropic FE |
| D — tensile | ISO 527-2 / D638 | upright (Z) | interlayer `E3`, `Z_t` | any cross-layer load |
| E — bend | ISO 178 [49] / D790 [48] | raster **not** in A–D | held-back validation | M5 blind test |
| F — notched | ASTM D5045 [45] (SENB or CT) | ≥2 orientations | `K_Ic` / `J_Ic` | LEFM, J-integral, phase-field |
| G — DCB | ASTM D5528 [84] | interlayer | Mode-I `G_Ic`, interface strength | cohesive zone model |
| H — mixed mode | D6671 [85] / D7905 [86] | interlayer | mixed-mode envelope | **only** if M6 goes mixed-mode |

n ≥ 5 for every row. A–E are the minimum for the elastic and failure-index
tiers; F and G are what make the fracture tier possible at all. H is explicitly
optional and should be dropped unless time allows.

Two caveats the sources raise about their own standards, which belong in the
SOP's method criticism:

- D5045's plane-strain/LEFM validity requirements are hard to satisfy in small
  FDM specimens [45]; check the size criteria and report honestly if `K_Q` does
  not qualify as a valid `K_Ic`. This is also why J-integral [73] is the more
  defensible route when PLA shows plasticity.
- D5528/D6671/D7905 are written for fibre-reinforced composite laminates
  [84][85][86]. Applying them to FDM interlayer interfaces is reasonable and is
  done in the literature [65], but the deviation must be stated as an adapted
  method, not presented as standard compliance.

**Build** `fdm_strength/experiment.py`: load raw rig output (CSV/Parquet) into
the `TestRun` schema, apply compliance correction, extract chord modulus, peak
force, failure strain, and — for F/G — compliance-calibration fracture energy;
emit per-configuration mean/SD/CoV.

**Gate**
CoV ≤ 15 % per configuration; compliance correction applied and documented;
reduced data written to a hashed Parquet with a provenance record attached.

### M4 — Isotropic 3D FEM baseline *(first point where "accurate" is meaningful)*

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
3. **Against M1 and M2.** Tensile stiffness within 0.1 % of the analytical bar;
   three-point-bend stiffness within 1 % of beam theory with shear correction;
   in-plane laminate modulus within 1 % of CLT for identical constants.
4. **CalculiX cross-check** [52]. Export the same mesh (C3D10), same BCs, same
   isotropic constants; peak displacement agrees within 0.5 %. This catches
   errors that both of your own implementations would share.

**Validation** Only now: compare to the M3 tensile and bend data. Keep this arm
in the final comparison rather than discarding it — [6] found isotropic FE
performs surprisingly well in the elastic range, and that result is part of the
SOP's answer about how much fidelity actually buys you.

### M5 — Orthotropic FEM + failure index *(the first genuinely new result)*

**Build**

- Constitutive model: full orthotropy needs 9 constants, which you do not have.
  Use the standard transversely-isotropic reduction about the raster direction —
  `E2 = E3`, `G12 = G13`, `ν12 = ν13`, `G23 = E2 / (2(1 + ν23))` — giving five
  independent constants `E1, E2, ν12, ν23, G12`, all measured in M3. This matches
  the orthotropic characterisation practice in [3][4][14][35].
- A per-element local material frame aligned with the raster direction.
- Failure post-processing, in this order:
  1. **Maximum stress** (`σ1/X`, `σ2/Y`, `τ12/S`) first — less smooth than a
     quadratic surface but it tells you *which* mode is critical, which is what
     you need while debugging.
  2. **Tsai–Wu** [76] as the review's "første anisotrope brudmodel". Note that
     the interaction coefficient `F12` is not directly measurable from A–D and
     is normally assumed; record the assumption.
  3. Report where the index **fails**, citing [39] and [29]. A documented
     breakdown is a result, not a defect in the work.

CalculiX supports orthotropic elasticity and local orientations directly
(`*ELASTIC, TYPE=ORTHOTROPIC` with `*ORIENTATION`), so the cross-check from M4
extends to this milestone unchanged.

**Gate — and this is the one that matters:**

Reproducing coupons A–D is a *consistency check*, not validation — those coupons
set the constants, so agreement is arithmetic, not evidence. The real gate is a
**blind prediction**: predict stiffness, peak force and failure location for the
held-back bend bars (row E) from M3 *and write the prediction down before
unblinding the measurements*.

**A blind prediction landing inside the experimental scatter band is your first
accurate simulation result.** Everything before it is infrastructure, and
everything after it is refinement.

### M6 — Fracture tier *(only after M5 validates)*

This is where the SOP's central question gets answered, and where the toolchain
constrains the choice — see §6. Ordered by cost:

1. **LEFM / J-integral post-processing** [71][72][73]. Compute `K` or `J` on the
   M5 orthotropic model for the notched F specimens, compare against measured
   `K_Ic`/`J_Ic`. No new solver machinery — a domain-integral post-process on a
   model you already have. Start here. [62] and [63] are the FDM-side
   references, and [63] is the workflow to copy if DIC is available.
2. **Cohesive zone at the interlayer interface** [79][38]. Insert a
   traction–separation law at layer interfaces, calibrated from the DCB data
   (row G). This is the physically natural model for FDM's known weak plane and
   the review rates it "meget relevant". [79] is specifically the reference for
   handling mesh-size effects, which is the practical failure mode here.
3. **Phase-field fracture** [80][81], with FDM validation from [18][66] and the
   parameter-identification method from [67]. Highest fidelity for crack path
   and branching, highest parameter cost (`G_c`, length scale `l_c`, and their
   identification).
4. **XFEM** [78][9][20] — treat as a literature comparison rather than an
   implementation target; see §6.

**Gate** Predicted crack path and peak load on a notched specimen that was not
used for calibration, against photographs or DIC fields.

### M7 — G-code-informed local fields *(the project-specific contribution)*

`gcodeparser` → normalised `ToolpathModel` → per-element raster orientation and
local porosity → spatially varying stiffness tensor. Closest prior work is
[30] and [26]; [10] is the voxel route.

**Run this as a controlled experiment, not an upgrade.** Per §2.5, the claim
under test is whether G-code-derived fields beat CAD-plus-homogenised-constants.
So: same specimen, same material model, same solver, same mesh density — only
the material field differs. Validate on a geometry where the toolpath genuinely
varies through the part (a curved or notched specimen), because on a straight bar
this degenerates to M5 and cannot show a difference either way.

A negative result here is publishable within the SOP and is directly supported by
[37]. Per the README, defer `pyGCodeDecode` [54] until timing-aware boundary
conditions are actually needed; `gcodeparser` is enough for geometry and
orientation.

---

## 6. What this toolchain can and cannot do

The solver stack constrains the fracture tier, and it is better to know now.

| Method | DOLFINx | CalculiX | Verdict |
| --- | --- | --- | --- |
| Orthotropic linear elasticity | Yes | Yes (`*ELASTIC, TYPE=ORTHOTROPIC`) | Both — use as cross-check |
| Failure index post-processing | Yes | Yes | Trivial either way |
| J-integral / domain integral | Yes (write the domain integral) | Limited | DOLFINx |
| Cohesive zone | Possible, needs interface elements or a mixed formulation | Limited cohesive support | Moderate work either way |
| Phase-field fracture | **Natural fit** — a coupled two-field variational problem, exactly what DOLFINx is for; Miehe's operator split [81] maps onto a staggered solve | No | DOLFINx |
| XFEM | Impractical — enrichment machinery DOLFINx does not provide | No | Use as literature comparison [9][20], or another platform |

The non-obvious consequence: **phase-field is easier in this repository than
XFEM**, which inverts the usual assumption that phase-field is the more advanced
option. The XFEM results in [9][20][27][64] should be cited as comparison, not
reimplemented. If phase-field in DOLFINx stalls, MOOSE [58] has it natively and
is the documented fallback — the review calls it overkill for the main SOP, which
is fair, but it is the right escape hatch for one benchmark case.

---

## 7. Test strategy

Replace the current tautological suite with three tiers, separated by pytest
markers so the fast tier stays usable:

- **`unit`** (milliseconds, no solver) — schema round-trips, unit conversions,
  analytical formulas against hand-computed values, CLT against hand-computed
  ABD terms, experimental-reduction logic against synthetic curves with known
  slope.
- **`verification`** (marked, needs DOLFINx/CalculiX) — convergence rates, patch
  test, analytical agreement, CLT-vs-FEM agreement, cross-solver agreement.
  These are the tests that would actually have caught a P1-tet bending error.
- **`validation`** (marked, needs data) — comparison against committed reduced
  coupon data with the tolerance bands from §3.2. Skipped when data is absent so
  the suite stays green on a clean checkout.

Extend `scripts/verify-environment.sh` to run `unit` always and `verification`
when the solver stack is present. Add CI that runs at least the `unit` tier.

---

## 8. Definition of done for the first accurate result

All of the following, together:

- [ ] Container pinned by digest; a provenance record exists for the run and its
      hashes resolve.
- [ ] All four M4 verification gates pass and are recorded in the run artefacts.
- [ ] Material constants come from measured coupons on the same printer and
      profile, with CoV ≤ 15 % and n ≥ 5, and carry an identified uncertainty [36].
- [ ] A prediction was written down **before** the comparison data was unblinded.
- [ ] The predicted stiffness and peak force fall inside the experimental scatter
      band, and the predicted failure region matches observation.
- [ ] Re-running from the recorded provenance on a clean checkout reproduces the
      numbers.

Anything short of this is a preliminary number, and should be labelled as one in
the SOP.

---

## 9. Sequencing

The software milestones are mostly serial; the physical campaign is not, and it
is the schedule driver.

```text
M0 foundations ──┐
M1 analytical  ──┼──► M4 isotropic FEM ──► M5 orthotropic ──► M6 fracture ──► M7 G-code
M2 CLT         ──┤         ▲                     ▲               ▲              ▲
                 │         │                     │               │              │
M3 print + test ─┴─────────┴─────────────────────┴───────────────┴──────────────┘
   A–E elastic/strength coupons · F notched · G DCB interlayer
   (start immediately — printing and testing dominates elapsed time)
```

M0–M2 are a few days of focused work. The M3 campaign — eight configurations at
n ≥ 5, printed in one batch with spares, plus testing — is weeks, and any process
problem found during testing sends you back to its start. Begin printing on day
one, and do not begin M6 planning until you know whether rows F and G are
actually feasible on the available rig [53].

---

## 10. Source map

Where each part of the plan comes from. Numbers refer to
`Kilder – alle kilder med metoder`.

| Roadmap element | Sources |
| --- | --- |
| Orthotropic constants, characterisation method | [3][4][7][12][14][32][34][35][36] |
| CLT as stiffness baseline | [1][3][42][64] |
| Isotropic FE surprisingly adequate in elastic range | [6] |
| Process parameters affect properties; profile is part of the material | [13][16] |
| Tsai–Wu and its FDM use | [76][1][29] |
| Documented limits of composite strength theory | [39][29] |
| Hashin damage / separate failure modes | [77][31] |
| Anisotropic plasticity if PLA yields visibly | [74][4][11] |
| LEFM, J-integral | [71][72][73][45][47][62][63] |
| Cohesive zone, mesh-size handling | [79][38][65] |
| Interlayer Mode-I fracture (DCB) | [65][84] |
| Mixed mode (optional) | [19][85][86] |
| Phase-field fracture, parameter identification | [80][81][18][66][67][69] |
| XFEM (comparison only) | [78][9][20][27][64] |
| RVE / homogenisation as intermediate step | [75][8][22][32][33][34][12] |
| Multiscale / defect-aware models | [5][70] |
| G-code / voxel reconstruction | [30][26][10][61][54] |
| Geometric detail is not automatically better | [37][70] |
| DIC as field-level validation | [82][31][63][28][41] |
| Uncertainty quantification in calibration | [36] |
| Tensile / flexural standards | [46][48][49][50] |
| Fracture standards | [45][47][84][85][86] |
| Tooling | [52][55][56][57][58][59][60][61][53] |
| Material datasheet (sanity check only) | [51] |
| Reviews for orientation and primary-source discovery | [43][44] |
| ML comparison arm (only with enough data) | [40][44] |

---

## 11. Immediate next commits

Ordered, each small enough to land independently:

1. Pin `DOLFINX_IMAGE` to a digest; record it in `.env.example` and the README.
2. Fix the `.gitignore` negations for `data/reference/` and `tests/data/`.
3. Add `units.py` with the declared convention and conversion helpers.
4. Add `schema.py` with `Specimen`, `MaterialProfile`, `PrintProfile`, `TestRun`.
5. Add `provenance.py` plus `fdm-strength provenance`; make `inspect` hash inputs.
6. Add pytest markers and drop the tautological version assertion.
7. Add `analytical.py` with the tension and three-point-bend reductions + tests.
8. Add `clt.py` with lamina → ABD → laminate moduli + hand-computed tests.
9. Add `mesh.py` with a parametric ISO 527-2 1A bar in Gmsh.
10. Add the DOLFINx isotropic solver and the convergence/patch-test verification.
11. Add the CalculiX export and the cross-solver comparison test.
12. Add the orthotropic constitutive model and failure-index post-processing.

In parallel, starting now: finalise the M3 specimen matrix and print it.
