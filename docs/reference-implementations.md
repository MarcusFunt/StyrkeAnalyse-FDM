# Reference implementations: what to build on, and what it costs

You do not have to derive every simulation method yourself. For most tiers in
`roadmap-first-accurate-results.md` there is an existing open-source
implementation that is readable, licensed for reuse, and close enough to the
project's stack to be worth adopting. This document records which ones, what
each actually contains, what it does *not* give you, and a realistic estimate of
the work to get it into this repository.

Effort is stated in **focused working days** for someone who knows the physics
but is new to the specific codebase. It covers reading the code, adapting it to
this project's schema and units, and writing the verification test — not just
getting an example to run.

All projects here were cloned and inspected directly; line counts are measured,
not estimated. Inspected at the state of the default branch, September 2026.

---

## 1. Summary table

| Roadmap tier | Project | License | LOC | What you get | Effort |
| --- | --- | --- | --- | --- | --- |
| M2 CLT | [lamipy](https://github.com/joaopbernhardt/lamipy) | MIT | 606 | ABD assembly, ply stresses, progressive failure | 1–2 d |
| M2 CLT (alt) | [composipy](https://github.com/rafaelpsilva07/composipy) | MIT | ~10.7 k | ABD, ply strain/stress, max-stress margins, buckling | 0.5–1 d |
| M5 failure index | [lamipy](https://github.com/joaopbernhardt/lamipy) `failurecriteria.py` | MIT | 303 | Tsai–Wu, max stress, max strain, Hashin (2D) | 1–2 d |
| M5 orthotropic FE | [comet-fenicsx](https://github.com/bleyerj/comet-fenicsx) orthotropic tour | CC-BY-SA-4.0 | 376 | UFL pattern for orthotropic stiffness | 2–4 d |
| M6 J-integral | *(none — write it)* | — | ~80 | — | 2–3 d |
| M6 cohesive zone | [comet-fenicsx](https://github.com/bleyerj/comet-fenicsx) CZM tours | CC-BY-SA-4.0 | 1 503 | Interface CZM + intrinsic CZM, full derivation | 8–12 d |
| M6 phase-field | [PhaseFieldX](https://github.com/CastillonMiguel/phasefieldx) | MIT | 18 062 | AT1/AT2, energy splits, fatigue, notched + 3PB examples | 2–3 d to run; 10–20 d to make FDM-relevant |
| M7 G-code → geometry | [VOLCO](https://github.com/FullControlXYZ/volco) | **GPL-3.0** | 5 442 | G-code → voxel → STL, voxel FEA, periodic homogenisation | 2–4 d |
| RVE homogenisation | VOLCO `fea/periodic.py` **or** comet-fenicsx | GPL-3.0 / CC-BY-SA | 399 / 363 | Periodic BCs → effective constants | 2–3 d / 5–7 d |
| DIC | [muDIC](https://github.com/PolymerGuy/muDIC) | MIT | 4 656 | B-spline DIC + virtual lab for self-validation | 2–4 d |
| Cross-check reference | [STORMFEA](https://github.com/micahtstoll-ai/STORMFEA) | MIT | TypeScript | Independent transversely-isotropic + interlayer implementation | read only |
| XFEM | *(nothing usable in this stack)* | — | — | — | do not attempt |

---

## 2. Per-tier analysis

### M2 — Classical laminate theory

**lamipy** — `clt.py` (303 lines) and `failurecriteria.py` (303 lines). Small
enough to read in full in an afternoon. `clt.py` gives `assemble_matrixQ`,
`assemble_matrixT`, `assemble_ABD`, `calc_stressCLT`, plus thermal and moisture
force terms. It also implements progressive failure by the ply-discount method,
which is more than the roadmap asks for at M2 but is directly useful at M5.

**composipy** — much larger (~10.7 k lines), pip-installable, actively
maintained, 294 commits, CI-tested. `core/strength.py` (425 lines) computes ply
strains and stresses in both laminate and material axes and produces
**max-stress margins** — but there is no Tsai–Wu in it, despite what some
summaries claim. I checked: the only criterion implemented is max stress.

**Recommendation.** Take composipy as a dependency if you want ABD quickly and
tested; take lamipy as the thing you actually read to understand what the code
is doing, and as an independent oracle for your own unit tests. The genuinely
cheap move is to write ~150 lines of your own CLT against your own schema and
verify it against *both* — two independent implementations agreeing on a
cross-ply ABD matrix is a strong test.

**What neither gives you:** the FDM interpretation. Deciding that a raster layer
*is* a lamina, and what its thickness and constants are, is your modelling work.

---

### M5 — Orthotropic 3D elasticity and failure index

**comet-fenicsx**, Jeremy Bleyer's *Computational Mechanics Numerical Tours with
FEniCSx*. This is the most valuable single resource in the list, because it is
written as teaching material: each tour is a `.py` and a matching `.md` with the
derivation. Relevant tours, measured:

| Tour | Lines (py) |
| --- | --- |
| `linear_problems/isotropic_orthotropic_elasticity` | 376 |
| `interfaces/czm_interface_only` (+ `utils.py`) | 481 + 347 |
| `interfaces/intrinsic_czm` | 675 |
| `homogenization/periodic_elasticity` | 363 |
| `nonlinear_problems/plasticity` | — (for Hill plasticity later) |

Two caveats that matter:

1. **The orthotropic tour is plane stress, 2D.** You need 3D solid orthotropy.
   The tour teaches the pattern — build the compliance matrix, invert, express
   as a UFL tensor — and the extension to a 6×6 solid stiffness is perhaps 60–80
   lines. But it is not copy-paste.
2. **There is no phase-field tour in the FEniCSx version.** The website text
   mentions phase-field, but the `tours/` tree contains no such directory; only
   `bound_constrained` references it. The phase-field demo exists in the older
   legacy-FEniCS `comet-fenics`, which will not run on DOLFINx.

**Failure index.** lamipy's `fs_tsaiwu_2D`, `fs_maxstress_2D`, `fs_hashin_2D` are
each ~30 lines and trivially readable. The plane-stress forms extend to a
per-element 3D evaluation directly. Expect a day to port and a day to test.

**CalculiX side is nearly free.** `*ELASTIC, TYPE=ORTHOTROPIC` plus
`*ORIENTATION` is built in, so the M4 cross-check extends to M5 for the cost of
writing the deck. This is a real argument for keeping the CalculiX arm.

---

### M6 — Fracture tier

**J-integral — write it yourself, and that is fine.** There is no packaged
domain-integral implementation for DOLFINx. There does not need to be: with UFL
the domain form is roughly 80 lines, and published FEniCS damage codes
(for example `MMousavi98/Statistical_GED`) do exactly this inline. Verify it
against a handbook `K_I` for a known geometry before trusting it. This is the
cheapest genuine fracture result in the whole plan — start the fracture tier
here.

**Cohesive zone — comet-fenicsx, and expect it to be hard.** Two tours:
`czm_interface_only` restricts cohesive behaviour to a predefined interface,
which is *exactly* the FDM interlayer case; `intrinsic_czm` puts cohesive
behaviour between all bulk elements. Together 1 503 lines including a 347-line
`utils.py` for the facet/orientation bookkeeping, which is the fiddly part.
Budget two weeks, not two days: interface element construction, facet
orientation, and the mesh-size sensitivity Turon et al. [79] describe are all
real work. But this is the model that matches the physics of FDM's known weak
plane, and the DCB coupons (row G) exist to calibrate it.

**Phase-field — PhaseFieldX, with one important caveat.** MIT licensed,
18 062 lines, structured as a real package (`Element/Phase_Field_Fracture/` with
`energy.py`, `g_degradation_functions.py`, `split_energy_stress_tangent_functions.py`,
`fatigue_degradation_functions.py`, and separate isotropic and anisotropic
solvers). It supports AT1 and AT2, spectral/deviatoric/isotropic energy splits,
and fatigue. It ships examples with *reference solutions* for:

- `1711_Single_Edge_Notched_Tension_Test`
- `1712_Single_Edge_Notched_Shear_Test`
- `1714_Three_point_bending`
- `1715_Symmetry_Center_notched_tension_test`

Those are the specimen geometries in the M3 matrix. Running your own notched
geometry through it is a few days of work.

**The caveat: PhaseFieldX's "anisotropic" is not material anisotropy.** I
checked the source. `solver_anisotropic.py` imports from
`Materials/elastic_isotropic.py`, and `Materials/` contains only an isotropic
model. "Anisotropic" there refers to the *tension/compression energy split*
(the standard phase-field usage), not to orthotropic stiffness. So for FDM you
would have to add (a) orthotropic elasticity into the split, and (b) a
direction-dependent `G_c` so cracks prefer the interlayer plane. That is the
actual research content of a phase-field arm — 2–4 weeks — and it is exactly
what [18], [66] and [67] did. Use PhaseFieldX as the verified isotropic base so
you are not also debugging the staggered solver.

**XFEM — do not attempt it here.** DOLFINx provides no enrichment machinery, and
CalculiX has none. The XFEM results in [9], [20], [27] and [64] belong in the
SOP as literature comparison. Trying to implement XFEM would consume the whole
project and produce nothing the phase-field or CZM arms do not.

---

### M7 — G-code to geometry: VOLCO is the significant find

[VOLCO](https://github.com/FullControlXYZ/volco) is the open-source
implementation of Gleadall's volume-conserving deposition model [10], the same
source already cited in the review. Measured: 5 442 Python lines, GPL-3.0,
Dockerfile, examples, 1 061 lines of tests.

It does more than the paper suggests. Besides G-code → voxel → STL, it ships a
complete voxel FEA submodule (2 398 lines):

| Module | Lines | Purpose |
| --- | --- | --- |
| `fea/solver.py` | 457 | Linear static hex8 solver, scipy sparse |
| `fea/periodic.py` | 399 | **Periodic BCs for RVE homogenisation** |
| `fea/boundary.py` | 287 | BC construction |
| `fea/io.py`, `mesh.py`, `analysis.py`, `viz.py`, `core.py` | 1 255 | Support |

`periodic.py` implements affine periodic constraints from a macroscopic strain
tensor with DOF elimination and rigid-body removal — that is a working RVE
homogenisation on the voxelised print. Which means the chain

> G-code → simulated bead geometry with voids → periodic RVE → effective
> orthotropic constants

already exists, in Python, and would otherwise be four to six weeks of work.
Its base material is isotropic, which is correct: the PLA bead material *is*
isotropic, and the anisotropy emerges from bead geometry and voids. That is
precisely the homogenisation argument.

**Effort: 2–4 days to run it and extract constants; 1–2 more to wire it into the
pipeline.** This is the best value-per-hour item on the list.

---

### DIC — muDIC

MIT, 4 656 lines, B-spline based, with a `vlab` (virtual lab) module that
generates synthetic speckle images with a known imposed deformation. That
matters: you can verify your DIC settings against a known answer before trusting
it on real specimens, which is the DIC equivalent of a patch test. Pure Python
on NumPy/SciPy/Numba, so it drops into this environment without trouble.

The software is the easy half. Optics, speckle pattern quality, lighting and
calibration are the work, and they are physical, not code.

---

### STORMFEA — read it, do not import it

[STORMFEA](https://github.com/micahtstoll-ai/STORMFEA) is an FDM-aware FEA for
3D-printed parts: transversely isotropic material with five constants, a
separate interlayer-interface failure check, Mohr–Coulomb interlayer shear,
C3D10 elements, SPR stress recovery, MIT licensed, 1 133 unit tests, and each
material constant cited to peer-reviewed literature with a confidence label.

It is Node.js/TypeScript, so it is not importable here. Its value is as an
**independent implementation of your M5**: somewhere to cross-check your numbers,
and a worked example of how to document where each material constant came from.
Its material-constant sourcing is a model for what §3.3 of the roadmap asks for.

---

## 3. Two cross-cutting problems to decide before copying anything

### 3.1 Licensing — this repository is MIT, and two key projects are not

| Project | License | Consequence |
| --- | --- | --- |
| lamipy, composipy, PhaseFieldX, muDIC, STORMFEA | MIT | Vendor or depend freely; keep the copyright notice |
| **VOLCO** | **GPL-3.0** | Copyleft. Linking it into an MIT package and distributing that would oblige you to release the combined work under GPL-3.0 |
| **comet-fenicsx** | **CC-BY-SA-4.0** | Share-alike. Copying substantial code obliges the derivative to carry the same licence |

Practical resolution, in order of preference:

1. **Run VOLCO as a separate tool.** Invoke it as its own process, consume the
   voxel array or STL it writes. Keeping it out of your import graph is the
   clean way to use it without relicensing your own code.
2. **Treat comet-fenicsx as teaching material.** The underlying mathematics is
   public and unencumbered; what CC-BY-SA covers is Bleyer's specific
   expression of it. Read the tour, understand it, write your own against your
   own schema — which you want to do anyway, since the tours target a different
   DOLFINx version. Cite it regardless; it earned the citation.
3. **Or relicense this repository to GPL-3.0** and stop worrying. For an SOP
   that is a perfectly reasonable choice — just make it deliberately.

None of this is a reason to avoid these projects. It is a reason to decide
*how* you use them before you paste anything.

### 3.2 DOLFINx version split

| Project | Targets |
| --- | --- |
| PhaseFieldX | `fenics-dolfinx==0.11.0` (current release) |
| comet-fenicsx | "These tours comply with `dolfinx` v.0.8.0" |

You cannot satisfy both without porting. 0.8 → 0.11 is mostly mechanical API
renaming, but it is real work and it is silent when you get it wrong.

**Recommendation:** pin the container to a 0.11.0 image *by digest* — which
roadmap §1.3 already requires for reproducibility — and port comet-fenicsx's
0.8 code forward as you adopt each tour. Do the pinning first. Debugging a
version mismatch while the base image is a moving `stable` tag is the worst of
both worlds.

---

## 4. Recommended adoption order

Ordered by value per hour, not by roadmap sequence:

1. **VOLCO** (2–4 d) — the largest single saving, and it de-risks M7 early.
   Run it standalone on a real G-code file in the first week, before committing
   to the rest of the plan, so you know the G-code arm is feasible.
2. **lamipy** (1–2 d) — read it, then write your CLT and use lamipy as the
   test oracle.
3. **comet-fenicsx orthotropic tour** (2–4 d) — the UFL pattern for M5.
4. **J-integral** (2–3 d) — write it; cheapest real fracture result.
5. **muDIC** (2–4 d) — only if the optical setup is realistic for you.
6. **PhaseFieldX** (2–3 d to run) — get the isotropic base working on your
   notched geometry before attempting anything FDM-specific.
7. **comet-fenicsx CZM** (8–12 d) — the highest-fidelity interlayer model, and
   the biggest single time sink. Do not start it until M5 has validated.

A realistic overall read: these projects turn the M2 and M5 software from
roughly two months into roughly two weeks. They do **not** shorten M3, and they
do not make M6 or M7 easy — those stay the hard parts, which is appropriate,
since that is where the SOP's contribution is.

---

## 5. Attribution

Credit every one of these, whether or not code is copied — reading an
implementation to understand a method is an intellectual debt regardless of
what ends up in the diff. Suggested practice:

- Add each to the SOP's source list with its repository URL, version or commit
  hash, and licence.
- Where code is vendored, keep the original licence header in the file and note
  the upstream commit in a comment.
- Where a project only informed your own implementation, say so in the module
  docstring: *"CLT assembly follows the approach in lamipy (MIT), verified
  against it."* That is honest, it is normal practice, and it is stronger than
  silence.
- Cite the paper as well as the code where both exist — VOLCO has [10],
  muDIC and PhaseFieldX both have accompanying publications.

Building on existing implementations is how computational mechanics is done.
Nobody rederives phase-field fracture to use it. What the SOP is assessed on is
the modelling decisions, the calibration, the validation design and the honest
reporting of where models fail — not whether you retyped a staggered solver.
