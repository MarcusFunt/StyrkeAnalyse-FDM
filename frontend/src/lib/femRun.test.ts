import { describe, expect, it } from "vitest";
import {
  MAX_FEM_PREVIEW_BYTES,
  loadFemRun,
  femEvidenceLabels,
  type FemRunDetailData,
} from "./femRun";

const runId = "123e4567-e89b-12d3-a456-426614174000";
const meshDigest = "a".repeat(64);
const fieldsXdmfDigest = "b".repeat(64);
const fieldsHdf5Digest = "c".repeat(64);
const resultMediaType = "application/vnd.styrkeanalyse.fem-result+json";
const provenanceMediaType = "application/vnd.styrkeanalyse.stage-provenance+json";
const previewMediaType = "application/vnd.styrkeanalyse.fem-field-preview+json";

function validPreview(meshSha256 = meshDigest): Uint8Array {
  return new TextEncoder().encode(JSON.stringify({
    schema_version: 1,
    mesh_sha256: meshSha256,
    coordinate_units: "mm",
    field_location: "boundary_element_average",
    preview_sampled: false,
    tetrahedron_count: 1,
    total_boundary_triangle_count: 4,
    points_mm: [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]],
    triangles: [
      [0, 1, 2], [0, 1, 3], [0, 2, 3], [1, 2, 3],
    ].map((vertices) => ({
      vertices,
      source_cell: 0,
      von_mises_stress_mpa: 10,
      axial_stress_mpa: 9,
      axial_displacement_mm: 0.01,
    })),
  }));
}

function sha256(bytes: Uint8Array): Promise<string> {
  return crypto.subtle.digest("SHA-256", bytes.slice().buffer as ArrayBuffer).then((digest) =>
    Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join(""),
  );
}

async function makeFixture(options: {
  previewBytes?: Uint8Array;
  previewMeshDigest?: string;
  includePreviewOutput?: boolean;
  includePreviewManifest?: boolean;
} = {}): Promise<{ fetcher: typeof fetch; runData: FemRunDetailData; previewSha: string }> {
  const previewBytes = options.previewBytes ?? validPreview(options.previewMeshDigest);
  const previewSha = await sha256(previewBytes);
  const provenanceBytes = new TextEncoder().encode(JSON.stringify({
    schema_version: 2,
    run_id: runId,
    image_reference: "styrkeanalyse-fdm:isotropic-fem",
    image_digest: `sha256:${"1".repeat(64)}`,
    dependency_lock_sha256: "2".repeat(64),
    contract_sha256: "3".repeat(64),
    git_commit: "4".repeat(40),
    git_dirty: false,
    solver_name: "DOLFINx",
    solver_version: "0.11.0.post0",
    mpi_ranks: 1,
    omp_threads: 1,
    openblas_threads: 1,
    runtime_versions: { dolfinx: "0.11.0.post0", gmsh: "4.13.1" },
    inputs: [],
    outputs: [
      { name: "result.json" },
      { name: "mesh.msh" },
      { name: "fields.xdmf" },
      { name: "fields.h5" },
      ...(options.includePreviewOutput === false ? [] : [{ name: "field-preview.json" }]),
    ],
  }));
  const provenanceSha = await sha256(provenanceBytes);
  const outputArtifacts = [
    { sha256: meshDigest, size_bytes: 128, media_type: "application/vnd.gmsh.msh" },
    { sha256: fieldsXdmfDigest, size_bytes: 256, media_type: "application/vnd.xdmf+xml" },
    { sha256: fieldsHdf5Digest, size_bytes: 512, media_type: "application/x-hdf5" },
    ...(options.includePreviewOutput === false ? [] : [{
      sha256: previewSha,
      size_bytes: previewBytes.byteLength,
      media_type: previewMediaType,
    }]),
    { sha256: provenanceSha, size_bytes: provenanceBytes.byteLength, media_type: provenanceMediaType },
  ];
  const envelope = {
    schema_version: 1,
    run_id: runId,
    stage_id: "fdm-l2-isotropic",
    specimen: { specimen_id: "SYN-T01", length_mm: 50, width_mm: 10, thickness_mm: 2 },
    material: { profile_id: "PLA-isotropic-v1", youngs_modulus_mpa: 2000, poissons_ratio: 0.35, sha256: "5".repeat(64) },
    boundary_conditions: { set_id: "gui-tensile-axial-v1", sha256: "6".repeat(64) },
    mesh: { sha256: meshDigest, cell_count: 1, max_cell_size_mm: 2.5, element_order: 1 },
    solver_metadata: {
      name: "DOLFINx", version: "0.11.0.post0", iteration_count: 1, residual_norm: 0,
      mpi_ranks: 1, omp_threads: 1, blas_threads: 1, allocated_cpus: 2,
    },
    fields: {
      displacement: "fields.xdmf:/displacement_mm",
      cauchy_stress: "fields.xdmf:/cauchy_stress_mpa",
      von_mises_stress: "fields.xdmf:/von_mises_stress_mpa",
    },
    verification_status: "not_assessed",
    artifacts: {
      "mesh.msh": { sha256: meshDigest, size_bytes: 128, media_type: "application/vnd.gmsh.msh" },
      "fields.xdmf": { sha256: fieldsXdmfDigest, size_bytes: 256, media_type: "application/vnd.xdmf+xml" },
      "fields.h5": { sha256: fieldsHdf5Digest, size_bytes: 512, media_type: "application/x-hdf5" },
      ...(options.includePreviewManifest === false ? {} : {
        "field-preview.json": { sha256: previewSha, size_bytes: previewBytes.byteLength, media_type: previewMediaType },
      }),
    },
    result: {
      reaction_force_n: 100,
      imposed_force_n: 100,
      measured_axial_displacement_mm: 0.05,
      nominal_stress_mpa: 5,
      nominal_strain: 0.001,
      volume_average_axial_stress_mpa: 5,
      peak_von_mises_stress_mpa: 5,
      axial_stress_uniformity_relative_range: 0,
      strain_energy_n_mm: 2.5,
    },
  };
  const resultBytes = new TextEncoder().encode(JSON.stringify(envelope));
  const resultSha = await sha256(resultBytes);
    const run = {
    id: runId,
    created_at: "2026-10-01T12:00:00Z",
    operation: "fdm-l2-isotropic",
    status: "succeeded",
    input_artifacts: [],
    result_artifact: { sha256: resultSha, size_bytes: resultBytes.byteLength, media_type: resultMediaType },
    output_artifacts: [
      { sha256: resultSha, size_bytes: resultBytes.byteLength, media_type: resultMediaType },
      ...outputArtifacts,
    ],
    stages: [{
      stage_id: "fdm-l2-isotropic",
      status: "succeeded",
      image_digest: `sha256:${"1".repeat(64)}`,
      git_commit: "4".repeat(40),
      omp_threads: 1,
      mpi_ranks: 1,
      openblas_threads: 1,
      input_artifacts: [],
      output_artifacts: [
        { sha256: resultSha, size_bytes: resultBytes.byteLength, media_type: resultMediaType },
        ...outputArtifacts,
      ],
    }],
  };
  const responses = new Map<string, Response>([
    [`/api/runs/${runId}`, new Response(JSON.stringify({ run }))],
    [`/api/artifacts/${resultSha}`, new Response(resultBytes)],
    [`/api/artifacts/${previewSha}`, new Response(previewBytes.slice().buffer as ArrayBuffer)],
    [`/api/artifacts/${provenanceSha}`, new Response(provenanceBytes)],
  ]);
  const fetcher = (async (input: RequestInfo | URL) => {
    const pathname = new URL(String(input), "http://localhost").pathname;
    return responses.get(pathname) ?? new Response(JSON.stringify({ error: "missing" }), { status: 404 });
  }) as typeof fetch;
  return { fetcher, runData: run as unknown as FemRunDetailData, previewSha };
}

describe("FEM Run inspection", () => {
  it("test_parse_fem_run_binds_preview_to_declared_output_and_mesh", async () => {
    const fixture = await makeFixture();
    const detail = await loadFemRun(runId, fixture.fetcher);

    expect(detail.run.id).toBe(runId);
    expect(detail.envelope.mesh.sha256).toBe(meshDigest);
    expect(detail.preview?.mesh_sha256).toBe(meshDigest);
    expect(detail.preview?.triangles[0].von_mises_stress_mpa).toBe(10);
    expect(detail.artifacts.map((artifact) => artifact.name)).toEqual([
      "mesh.msh", "fields.xdmf", "fields.h5", "field-preview.json", "provenance.json",
    ]);
    expect(detail.provenance.image_digest).toBe(`sha256:${"1".repeat(64)}`);
  });

  it("keeps results and declared downloads available when field preview is missing or malformed", async () => {
    const unlisted = await makeFixture({ includePreviewOutput: false });
    const missing = await loadFemRun(runId, unlisted.fetcher);
    expect(missing.preview).toBeNull();
    expect(missing.previewError).toMatch(/not bound|unavailable|declare exactly one/i);
    expect(missing.envelope.result.reaction_force_n).toBe(100);
    expect(missing.artifacts.map((artifact) => artifact.name)).toEqual([
      "mesh.msh", "fields.xdmf", "fields.h5", "provenance.json",
    ]);

    const malformed = await makeFixture({ previewBytes: new TextEncoder().encode("not JSON") });
    const invalid = await loadFemRun(runId, malformed.fetcher);
    expect(invalid.preview).toBeNull();
    expect(invalid.previewError).toMatch(/valid JSON/i);
    expect(invalid.artifacts.map((artifact) => artifact.name)).toContain("field-preview.json");

    const wrongMesh = await makeFixture({ previewMeshDigest: "f".repeat(64) });
    const mismatched = await loadFemRun(runId, wrongMesh.fetcher);
    expect(mismatched.preview).toBeNull();
    expect(mismatched.previewError).toMatch(/mesh digest/i);
    expect(mismatched.artifacts.map((artifact) => artifact.name)).toContain("mesh.msh");

    const legacy = await makeFixture({ includePreviewOutput: false, includePreviewManifest: false });
    const legacyDetail = await loadFemRun(runId, legacy.fetcher);
    expect(legacyDetail.preview).toBeNull();
    expect(legacyDetail.previewError).toMatch(/unavailable/i);
    expect(legacyDetail.artifacts.map((artifact) => artifact.name)).toContain("fields.h5");
  });

  it("keeps the scalar result and exact artifact links when the preview exceeds the viewer limit", async () => {
    const oversized = await makeFixture({ previewBytes: new Uint8Array(MAX_FEM_PREVIEW_BYTES + 1) });
    const detail = await loadFemRun(runId, oversized.fetcher);
    expect(detail.preview).toBeNull();
    expect(detail.previewError).toMatch(/16 MiB/i);
    expect(detail.envelope.result.nominal_stress_mpa).toBe(5);
    expect(detail.artifacts.map((artifact) => artifact.name)).toContain("field-preview.json");
  });

  it("test_fem_run_detail_labels_run_gate_and_validation_separately", () => {
    expect(femEvidenceLabels("succeeded", "not_assessed")).toEqual({
      execution: "Succeeded",
      solverVerification: "Not assessed for this Run",
      experimentalValidation: "Not validated against experiment",
    });
  });
});
