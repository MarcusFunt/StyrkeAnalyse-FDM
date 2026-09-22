# Glossary: the terms used in this project, explained

The other documents in `docs/` use a lot of shorthand. This one explains it in
plain language, roughly in the order the project meets it. §9 is a compact
alphabetical lookup for when you just need a reminder.

A few names get garbled easily, so for the record: the deposition simulator is
**VOLCO** (VOLume COnserving), the solver is **CalculiX**, and the interface
fracture model is **CZM** (Cohesive Zone Model).

---

## 1. The physical thing you are printing

**FDM / FFF** — Fused Deposition Modelling / Fused Filament Fabrication. The
same process: a nozzle melts plastic filament and draws lines of it, layer by
layer. "FDM" is a Stratasys trademark, "FFF" is the vendor-neutral term. The
literature uses both.

**Bead** (also *road*, *extrudate*, *filament*) — one extruded line of plastic.
Not a cylinder: it is squashed against the layer below, so its cross-section is
roughly a rectangle with rounded ends. A printed part is a stack of these.

**Layer** — one horizontal pass of beads. **Layer height** is its thickness,
typically 0.1–0.3 mm.

**Raster** / **raster angle** — the direction the infill beads run, measured
against the specimen's long axis. A 0° raster has beads along the loading
direction; 90° has them across it. This is the single most important variable
in the whole project, because it controls how strong the part is.

**Interlayer** (or *interlaminar*) — the bond between one layer and the next.
Beads within a layer are laid down hot against each other and fuse well. Between
layers, the lower one has cooled before the next arrives, so the bond is weaker.
**This is where FDM parts usually break.**

**Void** / **porosity** — the gaps left between beads because round-ish shapes
do not tile perfectly. A "solid" printed part is typically 90–98 % dense. Voids
reduce both stiffness and strength, and they are why a printed part is weaker
than the same plastic injection-moulded.

**Build orientation** — how the part sat on the bed while printing. "Flat" vs
"upright" (also called *Z-oriented*) matters enormously: an upright tensile
specimen is loaded straight across the interlayer bonds, and typically reaches
only 30–60 % of the flat specimen's strength.

**Seam** — the point where each perimeter loop starts and stops. A small
geometric defect that repeats on every layer, so it forms a vertical line of
weakness.

---

## 2. Describing how stiff and strong the material is

**Stress** (σ) — force divided by area, in MPa (N/mm²). **Strain** (ε) — how
much something stretched, as a fraction of its original length. Dimensionless.

**Young's modulus** (E) — stiffness. The slope of stress against strain in the
straight initial part of the curve. PLA is roughly 2.5–3.9 GPa depending on who
printed it and how, which is exactly why you must measure your own.

**Poisson's ratio** (ν) — when you stretch something it gets thinner. ν is how
much thinner, relative to how much longer. Around 0.35 for PLA.

**Shear modulus** (G) — stiffness against being skewed rather than stretched.

**Strength** — the stress at which it breaks. Written `X_t` (tensile strength
along direction 1), `Y_t` (along direction 2), `S` (shear strength). The `t`
means tensile; compressive strengths are usually different and larger.

### Why one number is not enough

**Isotropic** — the same in all directions. Steel, glass, injection-moulded
plastic. Needs just 2 constants (E and ν).

**Anisotropic** — direction-dependent. Wood, carbon fibre, and printed parts.

**Orthotropic** — anisotropic, but with three mutually perpendicular planes of
symmetry, like the grain directions in wood. Needs **9** independent constants:
`E1 E2 E3`, `G12 G13 G23`, `ν12 ν13 ν23`.

**Transversely isotropic** — orthotropic with a simplification: one axis is
special (here, along the beads) and the plane perpendicular to it behaves the
same in every direction. Needs only **5** constants. The roadmap uses this
reduction because 5 constants are measurable from four coupon types, and 9 are
not.

**Stiffness matrix** (often written `C` or `L`) — the full description, a 6×6
matrix relating the six stress components to the six strain components. The
engineering constants above are derived from it. Store the matrix, not just the
derived constants: the derivation is lossy if the material turns out not to fit
the assumed symmetry, and you will want to check whether it does.

**Compliance matrix** — the inverse of the stiffness matrix. Strains from
stresses rather than the other way round. Often easier to write down, because
its entries are directly `1/E1`, `-ν12/E1`, and so on.

---

## 3. Measuring it: the tests

**Coupon** / **specimen** — a deliberately simple test piece, printed to a
standard shape so results can be compared with other people's.

**Dogbone** — the classic tensile specimen shape: wide at the ends for the grips
to hold, narrow in the middle so it breaks where you are measuring.

**Tensile test** — pull until it breaks. Gives E, ν and tensile strength.
Standards: **ISO 527** (international) or **ASTM D638** (American).

**Three-point bending (3PB)** — rest a bar on two supports, push down in the
middle. Gives flexural modulus and strength. Standards: **ISO 178** or
**ASTM D790**. Useful because it produces tension on one face and compression on
the other, which is a different loading state from pure tension.

**Notched specimens** — a deliberate sharp cut, so that you control where the
crack starts and can measure how hard it is to make it grow:

- **SENB** — Single Edge Notched Bend. A 3PB bar with a notch cut in the tension
  face.
- **CT** — Compact Tension. A squat notched block pulled apart by two pins.
- **SCB** — Semi-Circular Bend. A half-disc with a notch, bent. Simpler to print
  and test than CT.
- **DCB** — Double Cantilever Beam. Two arms with a pre-crack between them,
  pulled apart like opening a book. Measures how strongly two layers are bonded
  — the most directly relevant test for FDM's weak plane.

**Crosshead displacement** — how far the testing machine's moving head travelled.
**Not** the same as how much your specimen stretched.

**Machine compliance** — the testing frame itself flexes under load. If you use
crosshead displacement as specimen strain, you are measuring the machine as well
as the specimen, and you will underestimate E by 10–30 %.

**Extensometer** — a clip-on gauge that measures the specimen's own stretch
directly, avoiding that error.

**Gauge length** (L₀) — the length over which strain is measured.

**Chord modulus** — E measured as the slope between two fixed strain points
(0.05 % and 0.25 % in ISO 527), rather than eyeballing "the straight bit". Fixed
points mean two people analysing the same curve get the same number.

**CoV** — Coefficient of Variation, the standard deviation divided by the mean,
as a percentage. How scattered your repeat tests are. FDM coupons typically run
5–15 %. It sets the accuracy floor: a model cannot be shown to be better than
the noise in the measurements it is compared against.

**DIC** — **Digital Image Correlation**. Spray the specimen with a random
speckle pattern, photograph it throughout the test, and let software track how
the speckles move. Instead of one strain number, you get a strain *map* over the
whole surface. Two families:

- *Subset-based* (muDIC, Ncorr): chop the image into small windows and track
  each one.
- *FE-based / global* (pyxel): describe the displacement on a finite element
  mesh. Slower, but the result lives in the same mathematical space as your
  simulation, so comparing them is direct and model updating follows naturally.

---

## 4. Fracture: how cracks behave

**Fracture mechanics** — the study of how cracks grow, as opposed to how
materials yield. The founding idea (Griffith, 1921) is energetic: a crack
advances when the energy released by doing so exceeds the energy needed to make
the new surfaces.

**Modes** — the three ways to load a crack:
- **Mode I** — opening, pulling the faces apart. Usually the most dangerous.
- **Mode II** — in-plane shear, sliding the faces past each other.
- **Mode III** — out-of-plane shear, tearing.
- **Mixed mode** — a combination, which is what real parts usually see.

**LEFM** — Linear Elastic Fracture Mechanics. Assumes the material is linear
elastic everywhere except a vanishingly small zone at the crack tip. Simple and
standardised, but invalid when the plastic zone is large — a real concern for
PLA, and the reason J-integral matters.

**K** — stress intensity factor. A single number characterising how severe the
stress field at the crack tip is. **K_Ic** is the critical value in Mode I: the
material's *fracture toughness*. Units MPa·√m.

**G** — energy release rate: energy released per unit of new crack area. **G_Ic**
is its critical value, in J/m². Related to K by `G = K²/E'`. (Unfortunately `G`
also means shear modulus — context tells you which.)

**J-integral** — a contour integral around the crack tip (in practice computed
as a *domain* integral over an area or volume, which is numerically better
behaved) that measures the crack driving force. Its key property is
*path-independence*: the answer does not depend on which contour you choose.
Crucially it stays valid with moderate plasticity, where K does not. **J_Ic** is
the critical value. Rice, 1968.

**Crack path** — where the crack actually goes. A model can predict the right
breaking force and still send the crack in the wrong direction, so this is
tracked as a separate result.

**Delamination** — layers separating. In FDM, interlayer failure.

---

## 5. Simulating it: the model ladder

Roughly in order of cost and fidelity.

**Analytical / classical statics** — closed-form formulas. `σ = F/A` for a bar;
`σ_f = 3FL/(2bh²)` for a bent beam. Instant, transparent, and the reference that
everything more complicated gets checked against. Blind to anisotropy and
cracks.

**CLT** — **Classical Laminate Theory**. Treat the part as a stack of thin
layers (*laminae*), each orthotropic and each rotated to its own angle. Assemble
the stack into an **ABD matrix** — `A` for in-plane stretching, `D` for bending,
`B` for the coupling between them — and you get the whole laminate's stiffness.
Borrowed from fibre composites; applies to FDM by treating each raster layer as
a lamina. Cheap, no mesh, and reported at about 1.5 % error on tensile modulus.

**FEM / FEA** — Finite Element Method / Analysis. Chop the geometry into small
**elements**, approximate the solution inside each with simple functions, and
solve the resulting large system of equations. The standard tool for anything
with real geometry.

**Mesh** — the collection of elements. **Mesh convergence**: refine the mesh
until the answer stops changing. If it does not stop changing, the answer is
meaningless.

**Element types** — naming differs between ecosystems:
- FEniCS/DOLFINx says **P1** (linear) and **P2** (quadratic), referring to the
  polynomial degree of the shape functions.
- CalculiX/Abaqus says **C3D4** (4-node linear tet), **C3D10** (10-node
  quadratic tet), **C3D8** (8-node linear hex/brick).

**Shear locking** — linear tetrahedra are artificially stiff in bending. They
converge smoothly and look perfectly healthy while giving a badly wrong answer.
This is why the roadmap insists on P2/C3D10 for the bending model.

**Boundary conditions (BCs)** — what you hold and what you push. **Dirichlet**
fixes displacement; **Neumann** applies a force or traction. Getting these to
represent the real test rig is where a lot of accuracy is won or lost.

### Failure criteria — "has it broken yet?"

These take a computed stress state and return a **failure index**: below 1 is
safe, at or above 1 means predicted failure.

**Maximum stress** — check each stress component against its own allowable,
independently. Crude, but it tells you *which* mode is critical, which is
invaluable while debugging.

**Tsai–Wu** — a quadratic surface in stress space, including interaction between
components. Widely used for composites. Needs an interaction coefficient `F12`
that is awkward to measure and is usually assumed.

**Tsai–Hill** — a related, slightly simpler quadratic criterion.

**Hashin** — separates failure into distinct physical modes rather than lumping
them into one surface. More informative, needs more parameters.

**Hill** — an anisotropic *yield* criterion (for plastic deformation, not
fracture). The anisotropic generalisation of **von Mises**, which is the
standard isotropic yield criterion.

A failure index tells you *whether* something breaks. It does not tell you where
the crack goes or how it grows — for that you need the models below.

### Fracture models

**CZM** — **Cohesive Zone Model**. Instead of a mathematically sharp crack,
place a *traction–separation law* on an interface: as the two faces pull apart,
the stress across them rises to a peak (the interface strength), then falls to
zero as the bond breaks. The area under that curve is the fracture energy `G_Ic`.
Physically natural for FDM, because the interlayer *is* a real interface with a
real bond strength you can measure with a DCB test. Main practical difficulty:
results are sensitive to element size unless handled carefully.

**XFEM** — eXtended Finite Element Method. Adds extra ("enriched") degrees of
freedom so a crack can cut through the middle of elements without re-meshing.
Powerful, but requires machinery that DOLFINx and CalculiX do not have, which is
why this project cites XFEM results rather than reproducing them.

**Phase-field fracture** — the modern alternative. Do not represent the crack as
a geometric object at all. Instead introduce a *damage field* `d` over the whole
body, smoothly varying from 0 (intact) to 1 (fully broken), so a crack is a thin
band of `d ≈ 1` rather than a surface. Cracks then nucleate, turn and branch on
their own by energy minimisation, with nothing tracking them. Costs: you need
the fracture energy `G_c` and a **length scale** `l_c` controlling how wide the
smeared crack is, and the computations are expensive. Variants **AT1** and
**AT2** differ in whether there is a purely elastic phase before damage starts.

**Energy split** — in phase-field, material should break in tension but not
under compression, so the strain energy is split into a part that drives damage
and a part that does not (*spectral*, *volumetric–deviatoric*/Amor, or none).
Confusingly, this split is often called the "anisotropic" model — **that means
tension/compression asymmetry, not material direction-dependence.** PhaseFieldX
uses the word in this sense, which is why it is not automatically suitable for
FDM.

**Staggered solve / operator split** — phase-field has two coupled unknown
fields (displacement and damage). Solving them simultaneously is unstable, so
you alternate: fix damage, solve displacement, fix displacement, solve damage,
repeat.

### Bridging scales

**RVE** — Representative Volume Element. A small chunk of the internal structure
(here: a few beads and the voids between them) that is big enough to be
representative of the average behaviour.

**Homogenisation** — compute how that RVE responds, then use the resulting
effective properties as a single smeared material at part scale. This is the
formal justification for treating a bead-and-void structure as an orthotropic
solid.

**Periodic boundary conditions** — the assumption that the RVE tiles infinitely,
so opposite faces of the cell deform compatibly. Standard for homogenisation.

**Voigt and Reuss bounds** — two simple estimates that bracket the truth. Voigt
assumes uniform strain (too stiff, upper bound); Reuss assumes uniform stress
(too soft, lower bound). **Any correct homogenisation result must lie between
them**, which makes this a free sanity check.

**Multiscale / FE²** — instead of precomputing effective properties, solve an
RVE problem at every integration point of the macro model, every step. Very
expensive, very general.

---

## 6. Trusting it: verification and validation

**Verification** — *am I solving the equations correctly?* Compared against
exact solutions and convergence rates. No experiments involved. A verification
failure is a bug in your code.

**Validation** — *am I solving the correct equations for this material?*
Compared against measurements. A validation failure is a modelling error.

Doing validation before verification is the classic trap: you tune material
constants to cancel out a numerical error, get good agreement on the specimen
you calibrated against, and the model then fails on everything else.

**Patch test** — put a simple uniform stress state through the model and check it
comes back exactly. If a bar under end load does not give `σ = F/A` everywhere,
nothing else it says can be trusted.

**MMS** — Method of Manufactured Solutions. Choose any function as the "true"
answer, substitute it into the governing equation to work out what source term
would produce it, then solve numerically and check the error shrinks at the
theoretically expected rate under refinement. A wrong rate means a bug.

**Convergence rate** — how fast error falls as elements shrink: error ≈ C·hᵖ,
where `h` is element size. P1 elements should give p = 2 in displacement, P2
should give p = 3. Getting a different rate is diagnostic.

**Cross-solver check** — run the same problem in two independent codes (here,
DOLFINx and CalculiX) and compare. Catches mistakes that a single
implementation would make consistently and invisibly.

**Blind prediction** — predict the result, write the prediction down, *then*
look at the measurement. Without this, it is impossible to distinguish between
a model that works and a model you adjusted until it agreed.

**Quantity of interest (QoI)** — the specific number being compared, named in
advance so the target cannot quietly move.

---

## 7. The software

### Solvers and frameworks

**FEniCS / FEniCSx / DOLFINx** — a framework where you write the PDE's weak
form in near-mathematical notation and it generates and compiles the solver
code. Confusing naming: **FEniCS** (legacy, imported as `dolfin`, final release
2019) and **FEniCSx** (the current rewrite, imported as `dolfinx`) are different,
incompatible codebases. Which one a piece of example code targets decides
whether it runs at all.

**UFL** — Unified Form Language. The Python-embedded notation used to write
those weak forms.

**Weak form / variational form** — the integral restatement of a PDE that FEM
actually solves. "Weak" because it demands less smoothness of the solution than
the original differential ("strong") form.

**PETSc** — the numerical library underneath, providing the linear and nonlinear
solvers.

**MPI** — Message Passing Interface, the standard for running one calculation
across many processes. Each process is a **rank**. Relevant detail: iterative
solvers are not bit-identical across different rank counts, so the rank count is
recorded with every result.

**CalculiX** — an independent open-source FE solver. Binary `ccx`. Uses
Abaqus-style `.inp` input decks, which means it can read files written by many
other tools. Used here as an independent cross-check, and it supports
orthotropic materials and local orientations natively.

**Gmsh** — mesh generator, with a Python API. Turns geometry into elements.

**MFront / TFEL / MGIS** — MFront is a code generator for material constitutive
laws (orthotropic elasticity, Hill plasticity, damage). MGIS is the glue that
loads a compiled MFront law into a solver such as DOLFINx.

### The tools in the survey

**VOLCO** — VOLume COnserving model. Reads G-code and simulates the actual
deposition of each bead, conserving extruded volume and accounting for how new
material merges with what is already there. Outputs the result as a **voxel**
grid. Also ships a voxel FEA module with periodic homogenisation.

**Voxel** — a 3D pixel: one cell of a regular 3D grid, either material or empty.
So **"voxel bead geometry"** means the printed part's real shape — beads, their
squashed cross-sections, and the voids between them — represented as a 3D array
of filled and empty cells, rather than as idealised CAD geometry.

**PhaseFieldX** — a phase-field fracture package built on DOLFINx, with notched
and three-point-bend examples and reference solutions. Isotropic material only.

**comet-fenicsx** — Jeremy Bleyer's *Numerical Tours of Computational Mechanics*:
worked, explained examples for DOLFINx, including orthotropic elasticity,
cohesive zone models and periodic homogenisation.

**fedoo** — a Python FE library whose `get_homogenized_stiffness()` returns the
full effective 6×6 from a periodic mesh in one call.

**fibergen** — FFT-based homogenisation. Works directly on voxel grids with no
meshing step, which suits VOLCO's output exactly.

**FFT-based homogenisation** — instead of meshing and solving a linear system,
exploit the regular grid and solve in Fourier space. Much faster for voxel data.

**ciclope** — converts voxel data into CalculiX-solvable `.inp` decks. Built for
micro-CT scans of bone, but the machinery is generic.

**muDIC**, **pyxel** — the two DIC packages (subset-based and FE-based
respectively). **Ncorr**, **DICe**, **OpenCorr** are alternatives in MATLAB and
C++.

**lamipy**, **composipy** — small Python libraries implementing CLT. lamipy also
has Tsai–Wu, Hashin, max stress and max strain.

**FullControl** — designs printer toolpaths directly and emits G-code, rather
than slicing a model. Lets you specify raster angle exactly instead of inferring
what a slicer decided.

**SciSlice**, **OrcaSlicer**, **PrusaSlicer** — slicers: programs that convert a
3D model into G-code. SciSlice is research-oriented with precise toolpath
control; the other two are mainstream.

**G-code** — the printer's instruction language. Mostly lines like
`G1 X10 Y20 E0.5`: move to a coordinate while extruding a given amount.

**STL** — the common 3D model file format: a mesh of triangles describing the
outer surface only.

---

## 8. Reproducibility and infrastructure

**Container** — a packaged, isolated environment holding an application and
every library it needs, so it runs identically anywhere. Used here because the
tools above require three mutually incompatible versions of FEniCS.

**Image** vs **container** — an *image* is the frozen filesystem and
configuration; a *container* is a running instance of one. Image is to container
as class is to object.

**Tag** vs **digest** — a tag (`:stable`, `:latest`) is a mutable label that can
point at different content tomorrow. A **digest** (`@sha256:…`) is an immutable
content hash. **For reproducible results, always pin by digest.**

**Docker** — the usual tool for building and running containers.
**Docker Compose** — runs several containers together on one machine, described
in a YAML file. **Kubernetes (K8s)** — orchestrates containers across a cluster
of machines, adding scheduling, retries and resource limits, at the cost of
substantial complexity.

**Bind mount** — making a folder on your machine visible inside a container.
Convenient for editing; a reproducibility hazard for producing results, because
the code that ran is then no longer determined by the image.

**Provenance** — the record of exactly what produced a result: code commit,
image digests, input hashes, parameters, solver versions, thread and rank counts.
Without it, a number cannot be reproduced or defended.

**SHA-256** — a hash function producing a short fingerprint of a file. Any change
to the file changes the fingerprint, so it proves which exact file was used.

**Schema** — a machine-checkable definition of what fields a data record must
have and what types they hold. Implemented here with **pydantic**, a Python
library that validates data against such definitions.

**Parquet** — a compressed, typed, columnar file format for tabular data. Better
than CSV because column types survive the round trip.

**HDF5 / XDMF / VTU** — file formats for simulation field data (stress and
displacement over a mesh), readable by **ParaView**, the standard open-source
visualisation tool.

**CI** — Continuous Integration: automatically running the test suite on every
push, so breakage is caught immediately.

---

## 9. Compact terminology lookup

| Term | Short meaning |
| --- | --- |
| ABD matrix | Laminate stiffness from CLT: A = in-plane, D = bending, B = coupling |
| Anisotropic | Properties depend on direction |
| AT1 / AT2 | Two phase-field variants; AT1 has a purely elastic phase first |
| Bead / road | One extruded line of plastic |
| BC | Boundary condition — what is held, what is loaded |
| C3D4 / C3D8 / C3D10 | CalculiX elements: linear tet / linear hex / quadratic tet |
| CalculiX (`ccx`) | Open-source FE solver using Abaqus-style `.inp` files |
| Chord modulus | E from the slope between two fixed strain points |
| CLT | Classical Laminate Theory — stack of orthotropic layers |
| Compliance (machine) | The test frame's own flex, which corrupts strain readings |
| Compliance matrix | Inverse of the stiffness matrix: strains from stresses |
| Container / image | Isolated runtime environment / its frozen filesystem |
| CoV | Coefficient of variation = SD / mean; scatter between repeats |
| CT | Compact Tension — a notched fracture specimen |
| CZM | Cohesive Zone Model — traction–separation law at an interface |
| DCB | Double Cantilever Beam — measures interlayer Mode-I toughness |
| Delamination | Layers separating |
| Digest | Immutable `sha256:` content hash of an image. Pin by this |
| DIC | Digital Image Correlation — full-field strain from photographs |
| Dogbone | Standard tensile specimen shape |
| DOLFINx / FEniCSx | Current FEniCS generation (`import dolfinx`) |
| E | Young's modulus — stiffness |
| Element | One small piece of the mesh |
| Extensometer | Clip-on gauge measuring the specimen's own stretch |
| FDM / FFF | Fused Deposition Modelling / Fused Filament Fabrication |
| FE² / multiscale | Solve an RVE at every macro integration point |
| FEM / FEA | Finite Element Method / Analysis |
| FEniCS (legacy) | Pre-2020 generation (`import dolfin`); incompatible with DOLFINx |
| FFT homogenisation | Homogenisation in Fourier space, direct on voxel grids |
| G | Shear modulus — *or* energy release rate. Context decides |
| G_Ic | Critical Mode-I energy release rate (J/m²) |
| G-code | Printer instruction language |
| Gmsh | Mesh generator |
| Hashin | Failure criterion separating distinct failure modes |
| Hill | Anisotropic yield criterion (plasticity) |
| Homogenisation | Replacing fine structure with equivalent smeared properties |
| Interlayer | The bond between layers — FDM's weak plane |
| Isotropic | Same in all directions |
| J-integral | Path-independent crack driving force; valid with some plasticity |
| K / K_Ic | Stress intensity factor / Mode-I fracture toughness |
| Kubernetes (K8s) | Cluster-scale container orchestration |
| Lamina / laminate | One layer / a stack of layers |
| Layer height | Thickness of one printed layer |
| LEFM | Linear Elastic Fracture Mechanics |
| Length scale (l_c) | Width of the smeared crack in a phase-field model |
| MFront / MGIS | Constitutive-law generator / loader for solvers |
| MMS | Method of Manufactured Solutions — a verification technique |
| Mode I / II / III | Crack opening / in-plane shear / out-of-plane shear |
| MPI / rank | Multi-process parallelism / one such process |
| Ncorr, DICe, OpenCorr | Alternative DIC packages |
| Orthotropic | Three symmetry planes; 9 independent constants |
| P1 / P2 | Linear / quadratic elements in FEniCS naming |
| Parquet | Typed, compressed columnar table format |
| ParaView | Visualisation tool for simulation fields |
| Patch test | Check a uniform stress state is reproduced exactly |
| Periodic BC | RVE faces deform as if the cell tiled infinitely |
| PETSc | Numerical solver library under DOLFINx |
| Phase-field | Crack as a smooth damage field, not a geometric surface |
| Poisson's ratio (ν) | Lateral thinning per unit stretching |
| Porosity / void | Gaps between beads |
| Provenance | Full record of what produced a result |
| pydantic | Python library for schema validation |
| QoI | Quantity of interest — the number being compared |
| Raster angle | Direction of infill beads relative to the load |
| RVE | Representative Volume Element |
| Schema | Machine-checkable data definition |
| SCB | Semi-Circular Bend — a simple notched fracture specimen |
| Seam | Where each perimeter loop starts; a repeating defect |
| SENB | Single Edge Notched Bend specimen |
| Shear locking | Linear elements being wrongly stiff in bending |
| Slicer | Converts a 3D model into G-code |
| Staggered solve | Alternating between displacement and damage fields |
| Stiffness matrix (C, L) | Full 6×6 stress–strain relation |
| STL | Triangle-mesh 3D model format |
| Strain (ε) | Relative deformation, dimensionless |
| Stress (σ) | Force per unit area, MPa |
| Tag | Mutable image label such as `:stable`. Do not pin results to it |
| Tsai–Wu / Tsai–Hill | Quadratic anisotropic failure criteria |
| Transversely isotropic | One special axis, isotropic plane; 5 constants |
| UFL | Notation for writing weak forms in FEniCS |
| Validation | Are these the right equations for this material? |
| Verification | Am I solving the equations correctly? |
| Voigt / Reuss bounds | Upper / lower bounds any homogenisation must respect |
| VOLCO | VOLume COnserving deposition simulator, G-code → voxels |
| von Mises | Standard isotropic yield criterion |
| Voxel | A 3D pixel; one cell of a regular 3D grid |
| Weak form | Integral form of a PDE that FEM solves |
| X_t / Y_t / S | Tensile strength along 1 / along 2 / shear strength |
| XDMF / HDF5 / VTU | Simulation field-data file formats |
| XFEM | Extended FEM — cracks cut through elements without remeshing |
| Z-oriented | Printed upright, loaded across the layers |

---

## 10. Where to go next

- `roadmap-first-accurate-results.md` — what gets built, in what order, and the
  gates each step has to pass.
- `reference-implementations.md` — the existing open-source projects behind each
  method, with effort estimates.
- `execution-environments.md` — why each tool runs in its own container, and how
  data passes between them.
