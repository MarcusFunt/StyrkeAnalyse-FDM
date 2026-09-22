# Reference implementations: what to build on, and what it costs

You do not have to derive every simulation method yourself. For nearly every
tier in `roadmap-first-accurate-results.md` there is an existing open-source
implementation worth building on. This document records which ones, what each
actually contains, what it does *not* give you, and a realistic estimate of the
work to get it into this repository.

Effort is stated in **focused working days** for someone who knows the physics
but is new to the specific codebase. It covers reading the code, adapting it to
this project's schema and units, and writing the verification test — not just
getting an example to run.

Every project listed was cloned and inspected directly; line counts and
capability claims are measured, not taken from READMEs. Inspected at the state
of each default branch, September 2026.

**Licensing is not a constraint on this project** — the repository will adopt
whatever licence the chosen dependencies require. §5 records what each project
imposes so the final choice is made deliberately, but it is not a reason to
prefer one tool over another. The real constraint is §6: the DOLFINx / legacy
FEniCS split.

---

## 1. Summary

### Core simulation tiers

| Tier | Project | Licence | LOC | Effort |
| --- | --- | --- | --- | --- |
| M2 CLT | [lamipy](https://github.com/joaopbernhardt/lamipy) | MIT | 606 | 1–2 d |
| M2 CLT (alt) | [composipy](https://github.com/rafaelpsilva07/composipy) | MIT | 10 742 | 0.5–1 d |
| M5 failure index | [lamipy](https://github.com/joaopbernhardt/lamipy) `failurecriteria.py` | MIT | 303 | 1–2 d |
| M5 orthotropic FE | [comet-fenicsx](https://github.com/bleyerj/comet-fenicsx) orthotropic tour | CC-BY-SA-4.0 | 376 | 2–4 d |
| M5 constitutive laws | [dolfinx_materials](https://github.com/bleyerj/dolfinx_materials) | CC-BY-SA-4.0 | 4 860 | 3–5 d |
| M6 J-integral | *(write it — ~80 lines of UFL)* | — | — | 2–3 d |
| M6 cohesive zone | [comet-fenicsx](https://github.com/bleyerj/comet-fenicsx) CZM tours | CC-BY-SA-4.0 | 1 503 | 8–12 d |
| M6 phase-field (isotropic) | [PhaseFieldX](https://github.com/CastillonMiguel/phasefieldx) | MIT | 18 062 | 2–3 d to run |
| M6 phase-field (**anisotropic**) | [anisotropic_phase-field_fracture](https://github.com/bin-mech/anisotropic_phase-field_fracture) | **none stated** | 1 835 | 5–10 d *(legacy FEniCS)* |
| M6 phase-field (alt) | [GPFniCS](https://github.com/Manishkumar923/GPFniCS) | see repo | 13 440 | *(legacy FEniCS)* |
| M7 G-code → geometry | [VOLCO](https://github.com/FullControlXYZ/volco) | GPL-3.0 | 5 442 | 2–4 d |
| RVE homogenisation (FE) | [fedoo](https://github.com/3MAH/fedoo) | GPL-3.0 | 67 137 | **1–2 d** |
| RVE homogenisation (FE, alt) | VOLCO `fea/periodic.py` | GPL-3.0 | 399 | 2–3 d |
| RVE homogenisation (FFT) | [fibergen](https://github.com/fospald/fibergen) | GPL-3.0 | 5 338 | 2–4 d |
| Voxel → CalculiX | [ciclope](https://github.com/ciclope-microFE/ciclope) | MIT | 4 419 | 1–2 d |
| DIC + identification | [pyxel](https://github.com/jcpassieux/pyxel) | CeCILL | 12 725 | 4–6 d |
| DIC (subset) | [muDIC](https://github.com/PolymerGuy/muDIC) | MIT | 4 656 | 2–4 d |
| XFEM | *(nothing usable in this stack)* | — | — | do not attempt |

### Supporting and adjacent tools

| Purpose | Project | Licence | Why it matters here |
| --- | --- | --- | --- |
| Controlled toolpath generation | [FullControl](https://github.com/FullControlXYZ/fullcontrol) | GPL-3.0 | Design specimen toolpaths directly, no slicer guesswork |
| G-code parsing (geometry) | [gcodeparser](https://github.com/AndyEveritt/GcodeParser) | MIT | Already the roadmap's choice |
| G-code parsing (+ motion/timing) | [pyGCodeDecode](https://github.com/FAST-LB/pyGCodeDecode) | see repo | Adds acceleration/jerk-aware motion planning |
| CalculiX → ParaView | [ccx2paraview](https://github.com/calculix/ccx2paraview) | GPL-3.0 | `.frd` → `.vtu`, needed for the CalculiX arm |
| CalculiX model building | [pycalculix](https://github.com/spacether/pycalculix) | MIT | Unmaintained — read, don't depend |
| Tensile data reduction | [matan](https://pypi.org/project/matan/) | see repo | Implements ISO 527-1 reduction directly |
| Tensile data batch analysis | [extrudion](https://github.com/azzarip/extrudion_py) | see repo | Batch modulus/peak extraction |
| Analytical bounds | [pyxel](https://github.com/jcpassieux/pyxel) `material.py` | CeCILL | Voigt/Reuss/Hill/Hashin–Shtrikman — sanity-check any RVE result |
| Cross-check reference | [STORMFEA](https://github.com/micahtstoll-ai/STORMFEA) | MIT | Independent FDM-aware transversely-isotropic implementation |
| Microstructure generation | [Microgen](https://github.com/3MAH/microgen) | GPL-3.0 | TPMS/lattice, not beads — only if geometry moves that way |
| Differentiable FE | [JAX-FEM](https://github.com/deepmodeling/jax-fem) | Apache-2.0 | Inverse/identification route if FEMU is pursued |

---

## 2. The pipeline is now fully covered by existing tools

The significant result of this second survey is that **no link in the chain
requires original infrastructure work**. Stated as a pipeline:

```text
FullControl / SciSlice  ──►  G-code  ──►  VOLCO  ──►  voxel bead geometry
                                                            │
                        ┌───────────────────────────────────┤
                        ▼                                   ▼
            fedoo / fibergen / VOLCO-periodic        ciclope mesh2voxelfe
                        │                                   │
              effective orthotropic C (6×6)          CalculiX .inp (C3D8)
                        │                                   │
                        ▼                                   ▼
        DOLFINx orthotropic model  ◄── cross-check ──►  CalculiX solve
                        │
                        ▼
        failure index (lamipy) │ J-integral │ CZM │ phase-field
                        │
                        ▼
        validation vs coupons ── pyxel/muDIC DIC fields
```

Every box has a working implementation. What remains genuinely yours is the
modelling judgement: which homogenisation is legitimate, how interlayer
weakness enters the model, how constants are calibrated with honest
uncertainty, and where each model stops being trustworthy. That is the right
division of labour for an SOP.

---

## 3. New findings that change the plan

### 3.1 The phase-field anisotropy gap has a published solution — in legacy FEniCS

The previous survey identified the key limitation of PhaseFieldX: its
"anisotropic" solver refers to the *tension/compression energy split*, not
material anisotropy. Its `solver_anisotropic.py` imports from
`Materials/elastic_isotropic.py`, and `Materials/` contains only an isotropic
model. For FDM you need orthotropic stiffness **and** a direction-dependent
`G_c` so cracks prefer the interlayer plane.

[bin-mech/anisotropic_phase-field_fracture](https://github.com/bin-mech/anisotropic_phase-field_fracture)
implements exactly that — 1 835 lines, anisotropy in both the surface energy
and the elastic strain energy, with its own `fem/` submodule for function
spaces, assembly and solving.

**But it is legacy FEniCS.** Its imports are `from dolfin import`, not
`from dolfinx`. The same is true of every other anisotropic or alternative
phase-field implementation found: `GPFniCS` (13 440 lines) and
`iitrabhi/fenics-phase-field-fracture` are both legacy, and Maurini's
`damage-course` VarFrac notebook — the canonical teaching implementation of
variational brittle fracture — is also `from dolfin`.

This is a genuine fork in the road. See §6.

The repository also carries **no licence file at all**, which legally means all
rights reserved. Reading it and citing it is fine; redistributing its code is
not. Since the plan is to write your own anisotropic extension anyway, use it
as the reference for *what the formulation is*, and cite the paper.

### 3.2 fedoo reduces RVE homogenisation to one function call

[fedoo](https://github.com/3MAH/fedoo) (3MAH, GPL-3.0, 67 137 lines) has
`fedoo/homogen/tangent_stiffness.py` (254 lines) and a 1 464-line
`constraint/periodic_bc.py`. Its own example is this short:

```python
mesh = fd.mesh.import_file("...msh")["tet4"]
material = fd.constitutivelaw.ElasticIsotrop(1e5, 0.3)
assembly = fd.Assembly.create(fd.weakform.StressEquilibrium(material), mesh)
L_eff = fd.homogen.get_homogenized_stiffness(assembly, meshperio=True)
```

`L_eff` is the full effective 6×6 stiffness matrix. Feed it a periodic mesh of
your bead mesostructure and you have the orthotropic constants, with no
periodic-BC bookkeeping of your own. This is the cleanest route to the
homogenisation step in the whole survey — **1–2 days**, versus 5–7 for porting
comet-fenicsx's periodic tour from DOLFINx 0.8.

It is part of a coherent suite with [Microgen](https://github.com/3MAH/microgen)
(microstructure generation and periodic meshing) and
[simcoon](https://github.com/3MAH/simcoon) (constitutive models, and a
`L_iso_props` helper for reading equivalent properties back out of an
`L_eff`). Microgen targets TPMS and lattices rather than extruded beads, so it
is only relevant if the specimen geometry moves that way — VOLCO remains the
right generator for bead mesostructure.

### 3.3 fibergen homogenises voxels directly — which is what VOLCO produces

[fibergen](https://github.com/fospald/fibergen) (GPL-3.0, 5 338 lines) is an
FFT-based homogenisation tool. FFT methods operate on **regular voxel grids**
natively, with no meshing step at all, and are substantially faster than FE for
this problem class.

VOLCO's output is a voxel matrix. The pairing is direct: VOLCO voxels →
fibergen → effective stiffness, skipping mesh generation entirely. Where fedoo
is the cleaner API, fibergen is the better fit for VOLCO's data structure, and
running both on the same voxel array gives you two independent homogenisations
to cross-check. [FFTHomPy](https://github.com/vondrejc/FFTHomPy) is a pure-Python
alternative that also computes guaranteed upper/lower bounds.

### 3.4 ciclope bridges voxels to CalculiX

[ciclope](https://github.com/ciclope-microFE/ciclope) (MIT, 4 419 lines) exists
to turn micro-CT scans into FE models, but the machinery is generic. Its
`core/voxelFE.py` (819 lines) provides `mesh2voxelfe`, which writes an ABAQUS
`.INP` with C3D8 elements — explicitly documented as solvable by CalculiX —
with material mapping driven by template files. `core/tetraFE.py` (479 lines)
does the same via tetrahedral meshing.

That is precisely the missing bridge between VOLCO's voxel output and this
repository's CalculiX arm, already written and tested. It also means the
CalculiX cross-check extends all the way to the G-code-derived geometry, which
is a stronger verification story than the roadmap currently claims.

### 3.5 dolfinx_materials opens the constitutive door

[dolfinx_materials](https://github.com/bleyerj/dolfinx_materials) (Bleyer,
4 860 lines) lets you define constitutive behaviours that UFL cannot express,
via three routes: pure Python/NumPy, JAX (with automatic tangent operators),
and **MFront** behaviours compiled through MGIS.

That last one matters. MFront has mature, tested implementations of orthotropic
elasticity, Hill anisotropic plasticity and various damage models. Rather than
hand-deriving a Hill plasticity tangent — the roadmap's fallback if PLA shows
visible yielding [74][4] — you compile an MFront behaviour and load it. The
package also supports FE², where the constitutive update comes from solving an
RVE, which is the [5]/[70] multiscale tier.

Cost: installing TFEL/MFront and MGIS on top of the DOLFINx image. Real, but
bounded, and it replaces weeks of constitutive-law implementation.

### 3.6 pyxel does DIC *and* identification

[pyxel](https://github.com/jcpassieux/pyxel) (Passieux, CeCILL, 12 725 lines) is
**FE-based** (global) DIC, not subset-based: the kinematic field is described on
a finite element mesh. That has a direct consequence for this project — the DIC
result lives in the same space as the simulation, so comparing measured and
predicted fields is a mesh-to-mesh comparison rather than an interpolation
exercise, and model updating (FEMU) follows naturally.

That is the machine for [36]'s method: identify constants from full-field data
with quantified uncertainty, rather than from a handful of scalar chord moduli.

Its `material.py` is a useful find on its own: `Hooke`, plus `voigt`, `reuss`,
`hill` and `hashin_shtrikman` bounds. **Any homogenisation result must lie
between the Voigt and Reuss bounds** — that is a free, instant sanity check on
whatever fedoo, fibergen or VOLCO returns, and worth wiring into the test suite.

muDIC remains the gentler entry point (MIT, subset-based, and its `vlab` module
generates synthetic speckle images with a known imposed deformation, so you can
verify your DIC settings against a known answer — the DIC equivalent of a patch
test). Suggested split: muDIC to learn and to validate the optical setup, pyxel
once you want identification.

### 3.7 FullControl replaces slicer guesswork for specimens

[FullControl](https://github.com/FullControlXYZ/fullcontrol) (GPL-3.0, 17 168
lines, 4 027 lines of tests) designs toolpaths directly as a list of state
changes and emits G-code — no CAD, no STL, no slicer deciding anything.

For a calibration coupon whose raster angle *is* the independent variable, this
removes an entire error source: you are no longer inferring what the slicer did,
you specified it. It is the same organisation that publishes VOLCO, so the
toolpath you design and the deposition you simulate come from one ecosystem.
This is a stronger option than SciSlice [61] for rows A–D of the specimen matrix,
and should be evaluated before the print batch is committed.

### 3.8 No FDM bead-RVE generator exists — and that is fine

Searching specifically for parametric FDM mesostructure/bead-RVE generators
turned up nothing usable: DRAGen, PyCMG and the Neper-based tools target
polycrystals, concrete and lattices. The RVE papers in the review [8][12][32][34]
each built their own geometry.

This is not a gap to fill by hand. VOLCO generates the bead geometry *physically*
from the actual toolpath, including inter-bead voids, which is better evidence
than a parametric idealisation of what you assume a bead cross-section looks
like. Generate, don't idealise.

---

## 4. Tier-by-tier notes

### M2 — Classical laminate theory

**lamipy** — `clt.py` (303 lines) and `failurecriteria.py` (303 lines), MIT,
readable in an afternoon. `assemble_matrixQ`, `assemble_matrixT`,
`assemble_ABD`, `calc_stressCLT`, plus thermal and moisture terms and
progressive failure by ply discount.

**composipy** — larger (10 742 lines), pip-installable, 294 commits, CI-tested.
`core/strength.py` (425 lines) gives ply strains and stresses in both laminate
and material axes and **max-stress margins** — but there is no Tsai–Wu in it,
despite claims to the contrary. I checked the source.

**Recommendation.** Write ~150 lines of your own CLT against your own schema and
verify against *both*. Two independent implementations agreeing on a cross-ply
ABD matrix is a strong test, and you need the schema integration anyway.

### M5 — Orthotropic elasticity and failure index

**comet-fenicsx** remains the best teaching resource: each tour is a `.py` plus
a `.md` with the derivation. Measured:

| Tour | Lines (py) |
| --- | --- |
| `linear_problems/isotropic_orthotropic_elasticity` | 376 |
| `interfaces/czm_interface_only` (+ `utils.py`) | 481 + 347 |
| `interfaces/intrinsic_czm` | 675 |
| `homogenization/periodic_elasticity` | 363 |
| `nonlinear_problems/plasticity` | — (for Hill plasticity) |

Two caveats: the orthotropic tour is **plane stress, 2D** (the 3D solid
extension is ~60–80 lines of UFL, taught but not given), and there is **no
phase-field tour** in the FEniCSx version — the `tours/` tree has none, only
`bound_constrained` mentions it. The phase-field demo exists only in legacy
`comet-fenics`.

**Failure index:** lamipy's `fs_tsaiwu_2D`, `fs_maxstress_2D`, `fs_maxstrain_2D`
and `fs_hashin_2D` are ~30 lines each; the plane-stress forms extend to
per-element 3D evaluation directly.

**CalculiX is nearly free here:** `*ELASTIC, TYPE=ORTHOTROPIC` with
`*ORIENTATION` is built in, so the M4 cross-check extends to M5 for the cost of
writing the deck.

### M6 — Fracture tier

**J-integral — write it, and start here.** No packaged domain-integral exists
for DOLFINx and none is needed: in UFL the domain form is ~80 lines, and
published FEniCS damage codes do it inline. Verify against a handbook `K_I`
before trusting it. Cheapest genuine fracture result in the plan.

**Cohesive zone — comet-fenicsx, and budget two weeks.** `czm_interface_only`
restricts cohesive behaviour to a predefined interface, which is exactly the
FDM interlayer case; `intrinsic_czm` puts it between all bulk elements. The
347-line `utils.py` handling facet orientation is the fiddly part, and porting
from 0.8 adds risk. This estimate is the least confident in the document.

**Phase-field — two-stage.** Get PhaseFieldX's isotropic base running on your
notched geometry first (2–3 days) so you are not debugging a staggered solver
and a new formulation simultaneously. It ships examples with reference
solutions for `1711_Single_Edge_Notched_Tension_Test`,
`1712_Single_Edge_Notched_Shear_Test`, `1714_Three_point_bending` and
`1715_Symmetry_Center_notched_tension_test` — the same geometries as the M3
matrix — and supports AT1/AT2, spectral/deviatoric/isotropic splits, and
fatigue. Then add orthotropic stiffness and direction-dependent `G_c`, using
bin-mech's formulation as the reference. That second stage is the research
content, 2–4 weeks, and is what [18], [66] and [67] did.

**XFEM — do not attempt.** DOLFINx has no enrichment machinery and CalculiX has
none. Keep [9], [20], [27] and [64] as literature comparison.

---

## 5. Licensing, for the record

Since the project will relicense as needed, this is bookkeeping rather than a
decision gate. The effective floor is **GPL-3.0**: VOLCO, fedoo, fibergen,
FullControl and Microgen are all GPL-3.0, so any distributed combination lands
there. That is a perfectly reasonable licence for this work.

Two entries need care for different reasons:

- **comet-fenicsx and dolfinx_materials are CC-BY-SA-4.0.** Share-alike, and
  awkward when applied to code. You will be rewriting the orthotropic tour for
  3D and porting from 0.8 anyway, so this resolves itself.
- **bin-mech/anisotropic_phase-field_fracture has no licence file**, which means
  all rights reserved — more restrictive than any of the above. Read it, cite
  the paper, write your own.
- **pyxel is CeCILL**, a French GPL-compatible licence. Fine alongside GPL-3.0.

---

## 6. The real constraint: DOLFINx vs legacy FEniCS

This, not licensing, is the decision that shapes the project.

| Project | Stack |
| --- | --- |
| PhaseFieldX | `fenics-dolfinx==0.11.0` (current) |
| comet-fenicsx | DOLFINx 0.8.0 |
| dolfinx_materials | DOLFINx |
| **anisotropic_phase-field_fracture** | **legacy FEniCS** (`from dolfin`) |
| **GPFniCS** | **legacy FEniCS** |
| **Maurini `damage-course` / VarFrac** | **legacy FEniCS** |

Legacy FEniCS (2019.1) and DOLFINx are different codebases with incompatible
APIs. The anisotropic phase-field work — the part most specific to FDM — sits
entirely on the legacy side.

Three options:

1. **Stay on DOLFINx; port the formulation, not the code.** Read bin-mech's
   implementation, reimplement the anisotropic surface-energy and strain-energy
   terms on top of PhaseFieldX. Most work, cleanest result, and the
   reimplementation is defensible SOP content in its own right.
2. **Add a second container with legacy FEniCS 2019.1** and run the phase-field
   arm there. The repository already uses Docker Compose; adding a second
   service is cheap. You lose a shared codebase between arms but gain working
   code immediately. **This is the pragmatic choice if the phase-field arm is
   time-boxed.**
3. **Drop the anisotropic phase-field arm**, use isotropic PhaseFieldX as a
   benchmark, and put the fracture effort into the cohesive-zone interlayer
   model instead — which is arguably the better physics for FDM anyway, since
   the weak plane is a real interface rather than a smeared anisotropy.

Whichever is chosen, note the smaller version issue too: comet-fenicsx targets
0.8.0 while PhaseFieldX targets 0.11.0. Pin the container to 0.11.0 **by
digest** — roadmap §1.3 already requires this — and port comet's code forward
tour by tour. Debugging an API mismatch against a moving `stable` tag is the
worst of both worlds.

---

## 7. Recommended adoption order

By value per hour, not by roadmap sequence:

1. **VOLCO** (2–4 d) — largest single saving, and running it on real G-code in
   week one tells you whether the G-code arm is feasible before you commit to
   the rest of the plan.
2. **fedoo** (1–2 d) — `get_homogenized_stiffness` turns the RVE tier into a
   function call. Sanity-check the result against pyxel's Voigt/Reuss bounds.
3. **ciclope** (1–2 d) — voxel → CalculiX `.inp`, completing the cross-check
   path for G-code-derived geometry.
4. **lamipy** (1–2 d) — read it, write your CLT, use it as the test oracle.
5. **FullControl** (1–2 d) — evaluate before the print batch is committed;
   afterwards is too late.
6. **comet-fenicsx orthotropic tour** (2–4 d) — the UFL pattern for M5.
7. **J-integral** (2–3 d) — write it; cheapest real fracture result.
8. **muDIC** (2–4 d), then **pyxel** if identification is pursued.
9. **PhaseFieldX** (2–3 d to run) — isotropic base only, at first.
10. **comet-fenicsx CZM** (8–12 d) — highest-fidelity interlayer model, biggest
    time sink. Not before M5 validates.
11. **dolfinx_materials + MFront** — only if Hill plasticity or FE² is actually
    needed.

Realistic read: these projects turn the M2, M5 and homogenisation work from
roughly two to three months into roughly two to three weeks. They do **not**
shorten M3, the physical campaign. And they do not make the anisotropic
fracture arm easy — that stays the hard part, which is appropriate, since it is
where the contribution is.

---

## 8. Attribution

Credit every one of these, whether or not code is copied — reading an
implementation to understand a method is an intellectual debt regardless of what
ends up in the diff. Practice:

- Add each to the SOP's source list with repository URL, commit hash and licence.
- Where code is vendored, keep the original licence header and note the upstream
  commit in a comment.
- Where a project only informed your own implementation, say so in the module
  docstring: *"CLT assembly follows the approach in lamipy (MIT), verified
  against it."* That is honest, normal practice, and stronger than silence.
- Cite the paper as well as the code where both exist — VOLCO has [10], and
  muDIC, pyxel, PhaseFieldX, fedoo, ciclope, fibergen and JAX-FEM all have
  accompanying publications.

Building on existing implementations is how computational mechanics is done.
Nobody rederives phase-field fracture to use it. What the SOP is assessed on is
the modelling decisions, the calibration, the validation design and the honest
reporting of where models fail — not whether you retyped a staggered solver.
