# GUI FEM Workflow Design

## Goal

Let a researcher configure and submit the existing `fdm-l2-isotropic` tensile stage in the web GUI, then inspect that immutable Run's solver-produced mesh and field preview, scalar results, provenance, and verification state.

## User and constraints

- The audience is a researcher preparing synthetic and physical specimen analysis.
- The server-owned stage registry remains the only source of solver images, commands, and resource policy.
- FEM inputs are sealed in the canonical `request.json` input artifact and submitted through the existing persistent asynchronous job API.
- A successful Run is not equivalent to a passed solver-verification gate or an experimentally validated model.
- The exact Gmsh mesh and full XDMF/HDF5 fields remain downloadable immutable artifacts. Browser visualization is a bounded surface preview and is not a replacement for the full field data.

## Design

Add a Finite element page in the existing GUI. Its first form targets only the supported rectangular tensile/isotropic stage, exposes specimen ID and dimensions, material profile ID and isotropic material constants, axial force, mesh size, and P1/P2 element order, and submits only `operation`, the SHA-256-addressed canonical request file, empty generic parameters, and no upstream Runs. The current server-owned stage continues to enforce execution policy.

The runner currently returns scalar results and the Run artifact references, while DOLFINx writes complete field data in XDMF/HDF5. Add one explicit `field-preview.json` stage artifact containing the real generated boundary triangles and their element-averaged von Mises stress, axial stress, and axial displacement. Cap the preview at 20,000 deterministically sampled surface triangles and label sampled previews. Hash and record the preview alongside the existing exact mesh/field outputs. The UI renders this surface preview with field selection, rotate controls, mesh edges, units, min/max values, and links to download the exact mesh and complete field files.

After asynchronous submission, the GUI reports queued/running/succeeded/failed status. On success it fetches the immutable Run and full result artifact by content digest, verifies the preview is one of the Run's declared output artifacts, and shows scalar results, solver/material/boundary/mesh metadata, image/source/dependency provenance, and artifact hashes. The verification panel reports the Run's explicit `verification_status` (currently `not_assessed`), explains that M4 is a separate solver-method gate, and keeps experimental model validation as a separate not-yet-established state.

## Acceptance criteria

1. A user can submit an isotropic rectangular tensile solve from the GUI using explicit geometry, material, load, and mesh settings.
2. Queue, running, succeeded, and failed states are visible; a failed job shows the runner's error.
3. A successful Run displays scalar output, an interactive visualization derived from that Run's exact solver mesh/fields, exact mesh/XDMF/HDF5 downloads, immutable provenance, and a truthful verification/validation status.
4. A Run's preview digest must be declared in the immutable Run output list and match the preview manifest; missing, malformed, oversized, or unlisted preview data fails closed in the UI/runner while exact artifact downloads remain available.
5. Visualization clearly identifies its surface element-average approximation and never presents it as a full-volume field.
6. The UI does not send image references, commands, or resource limits.
7. Existing baseline, campaign, Run, replay, and M4 verification behavior remains intact.

## Out of scope

- Orthotropic stages, bending, blind prediction, experimental calibration, FEM-vs-experiment conclusions, and full-volume browser rendering.
- Browsing every historical Run from other browsers; this milestone opens and inspects Runs submitted in the current GUI session.
- Editing or replacing immutable Runs.
