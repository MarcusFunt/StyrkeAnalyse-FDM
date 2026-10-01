export const MAX_FEM_PREVIEW_BYTES = 16 * 1024 * 1024;
const MAX_FEM_METADATA_BYTES = 4 * 1024 * 1024;
const SHA256 = /^[0-9a-f]{64}$/;
const FEM_RESULT_MEDIA_TYPE = "application/vnd.styrkeanalyse.fem-result+json";
const FEM_PREVIEW_MEDIA_TYPE = "application/vnd.styrkeanalyse.fem-field-preview+json";
const PROVENANCE_MEDIA_TYPE = "application/vnd.styrkeanalyse.stage-provenance+json";

export interface FemArtifactReference {
  sha256: string;
  size_bytes: number;
  media_type: string;
}

export interface FemRunRecord {
  id: string;
  created_at: string;
  operation: "fdm-l2-isotropic";
  status: "succeeded" | "failed";
  result_artifact: FemArtifactReference;
  input_artifacts: FemArtifactReference[];
  output_artifacts: FemArtifactReference[];
  stages: Array<{
    stage_id: string;
    status: "succeeded" | "failed";
    image_digest: string;
    git_commit: string;
    omp_threads: number;
    mpi_ranks: number;
    openblas_threads: number;
    duration_ms: number;
    memory_limit_bytes: number;
    input_artifacts: FemArtifactReference[];
    output_artifacts: FemArtifactReference[];
  }>;
}

export interface FemFieldPreviewTriangle {
  vertices: [number, number, number];
  source_cell: number;
  von_mises_stress_mpa: number;
  axial_stress_mpa: number;
  axial_displacement_mm: number;
}

export interface FemFieldPreview {
  schema_version: 1;
  mesh_sha256: string;
  coordinate_units: "mm";
  field_location: "boundary_element_average";
  preview_sampled: boolean;
  tetrahedron_count: number;
  total_boundary_triangle_count: number;
  points_mm: Array<[number, number, number]>;
  triangles: FemFieldPreviewTriangle[];
}

export interface FemResultEnvelope {
  schema_version: 1;
  run_id: string;
  stage_id: "fdm-l2-isotropic";
  specimen: Record<string, unknown>;
  material: Record<string, unknown>;
  boundary_conditions: Record<string, unknown>;
  mesh: Record<string, unknown> & { sha256: string; cell_count: number };
  solver_metadata: Record<string, unknown>;
  fields: Record<string, string>;
  verification_status: string;
  artifacts: Record<string, FemArtifactReference>;
  result: Record<string, number>;
}

export interface FemRunProvenance {
  schema_version: 2;
  run_id: string;
  image_reference: string;
  image_digest: string;
  base_image_reference: string | null;
  dependency_lock_sha256: string;
  contract_sha256: string;
  git_commit: string;
  git_dirty: boolean | null;
  solver_name: string;
  solver_version: string;
  mpi_ranks: number;
  omp_threads: number;
  openblas_threads: number;
  cpu_count: number;
  memory_limit_bytes: number;
  runtime_versions: Record<string, string>;
  inputs: Array<Record<string, unknown>>;
  outputs: Array<Record<string, unknown>>;
}

export interface FemArtifactDownload {
  name: string;
  sha256: string;
  size_bytes: number;
  media_type: string;
}

export interface FemRunDetailData {
  run: FemRunRecord;
  envelope: FemResultEnvelope;
  preview: FemFieldPreview;
  provenance: FemRunProvenance;
  artifacts: FemArtifactDownload[];
}

interface FemResultArtifactEnvelope {
  schema_version: 1;
  run_id: string;
  stage_id: "fdm-l2-isotropic";
  result: Record<string, unknown>;
  [key: string]: unknown;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function requireRecord(value: unknown, label: string): Record<string, unknown> {
  if (!isRecord(value)) throw new Error(`${label} is malformed.`);
  return value;
}

function finiteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isArtifactReference(value: unknown): value is FemArtifactReference {
  return isRecord(value) &&
    typeof value.sha256 === "string" && SHA256.test(value.sha256) &&
    Number.isSafeInteger(value.size_bytes) && Number(value.size_bytes) >= 0 &&
    typeof value.media_type === "string" && value.media_type.length > 0;
}

function requireArtifactReference(value: unknown, label: string): FemArtifactReference {
  if (!isArtifactReference(value)) throw new Error(`${label} artifact reference is malformed.`);
  return value;
}

function requireUniqueArtifact(
  artifacts: FemArtifactReference[],
  mediaType: string,
  label: string,
): FemArtifactReference {
  const matches = artifacts.filter((artifact) => artifact.media_type === mediaType);
  if (matches.length !== 1) throw new Error(`Run must declare exactly one ${label} artifact.`);
  return matches[0];
}

async function readBoundedBytes(response: Response, maximumBytes: number, label: string): Promise<Uint8Array> {
  const declaredLength = Number(response.headers.get("Content-Length"));
  if (Number.isFinite(declaredLength) && declaredLength > maximumBytes) {
    throw new Error(`${label} exceeds the ${maximumBytes === MAX_FEM_PREVIEW_BYTES ? "16 MiB preview" : "metadata"} size limit.`);
  }
  if (!response.body) throw new Error(`${label} response body is empty.`);
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > maximumBytes) {
        await reader.cancel();
        throw new Error(`${label} exceeds the ${maximumBytes === MAX_FEM_PREVIEW_BYTES ? "16 MiB preview" : "metadata"} size limit.`);
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return bytes;
}

async function artifactBytes(
  fetcher: typeof fetch,
  reference: FemArtifactReference,
  maximumBytes: number,
  label: string,
): Promise<Uint8Array> {
  const response = await fetcher(`/api/artifacts/${reference.sha256}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`Could not load ${label} artifact.`);
  const bytes = await readBoundedBytes(response, maximumBytes, label);
  if (bytes.byteLength !== reference.size_bytes) throw new Error(`${label} artifact size does not match the immutable Run.`);
  if (await sha256(bytes) !== reference.sha256) throw new Error(`${label} artifact digest does not match the immutable Run.`);
  return bytes;
}

async function sha256(bytes: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", bytes.slice().buffer as ArrayBuffer);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function parseJsonBytes(bytes: Uint8Array, label: string): unknown {
  try {
    return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)) as unknown;
  } catch {
    throw new Error(`${label} is not valid JSON.`);
  }
}

export function parseFemFieldPreview(
  bytes: Uint8Array,
  expectedMeshSha256: string,
  cellCount: number,
): FemFieldPreview {
  if (bytes.byteLength > MAX_FEM_PREVIEW_BYTES) {
    throw new Error("FEM field preview exceeds the 16 MiB viewer limit.");
  }
  const preview = requireRecord(parseJsonBytes(bytes, "FEM field preview"), "FEM field preview");
  const expectedKeys = [
    "coordinate_units", "field_location", "mesh_sha256", "points_mm", "preview_sampled",
    "schema_version", "tetrahedron_count", "total_boundary_triangle_count", "triangles",
  ].sort();
  if (Object.keys(preview).sort().join("\0") !== expectedKeys.join("\0")) {
    throw new Error("FEM field preview has an unsupported schema.");
  }
  if (
    preview.schema_version !== 1 || preview.mesh_sha256 !== expectedMeshSha256 ||
    preview.coordinate_units !== "mm" || preview.field_location !== "boundary_element_average"
  ) {
    throw new Error("FEM field preview schema or mesh digest does not match the Run.");
  }
  if (
    preview.tetrahedron_count !== cellCount || !Number.isSafeInteger(preview.tetrahedron_count) ||
    !Number.isSafeInteger(preview.total_boundary_triangle_count) ||
    Number(preview.total_boundary_triangle_count) <= 0 || typeof preview.preview_sampled !== "boolean"
  ) {
    throw new Error("FEM field preview counts are invalid or do not match the mesh.");
  }
  const points = preview.points_mm;
  const triangles = preview.triangles;
  if (
    !Array.isArray(points) || points.length < 3 || points.length > MAX_FEM_PREVIEW_BYTES / 24 ||
    !Array.isArray(triangles) || triangles.length === 0 || triangles.length > 20_000 ||
    Number(preview.total_boundary_triangle_count) < triangles.length ||
    preview.preview_sampled !== (Number(preview.total_boundary_triangle_count) > triangles.length)
  ) {
    throw new Error("FEM field preview contains invalid point or triangle counts.");
  }
  const parsedPoints = points.map((point) => {
    if (!Array.isArray(point) || point.length !== 3 || !point.every(finiteNumber)) {
      throw new Error("FEM field preview contains a non-finite coordinate.");
    }
    return point as [number, number, number];
  });
  const parsedTriangles = triangles.map((triangle): FemFieldPreviewTriangle => {
    const item = requireRecord(triangle, "FEM field preview triangle");
    const triangleKeys = [
      "axial_displacement_mm", "axial_stress_mpa", "source_cell", "vertices", "von_mises_stress_mpa",
    ].sort();
    if (Object.keys(item).sort().join("\0") !== triangleKeys.join("\0")) {
      throw new Error("FEM field preview contains an unsupported triangle record.");
    }
    const vertices = item.vertices;
    if (
      !Array.isArray(vertices) || vertices.length !== 3 ||
      vertices.some((index) => !Number.isSafeInteger(index) || Number(index) < 0 || Number(index) >= parsedPoints.length) ||
      new Set(vertices).size !== 3
    ) {
      throw new Error("FEM field preview contains an invalid vertex index.");
    }
    if (!Number.isSafeInteger(item.source_cell) || Number(item.source_cell) < 0 || Number(item.source_cell) >= cellCount) {
      throw new Error("FEM field preview contains an invalid source cell.");
    }
    for (const key of ["von_mises_stress_mpa", "axial_stress_mpa", "axial_displacement_mm"]) {
      if (!finiteNumber(item[key])) throw new Error("FEM field preview contains a non-finite field value.");
    }
    if (Number(item.von_mises_stress_mpa) < 0) throw new Error("FEM field preview contains negative von Mises stress.");
    return {
      vertices: vertices as [number, number, number],
      source_cell: Number(item.source_cell),
      von_mises_stress_mpa: Number(item.von_mises_stress_mpa),
      axial_stress_mpa: Number(item.axial_stress_mpa),
      axial_displacement_mm: Number(item.axial_displacement_mm),
    };
  });
  return {
    schema_version: 1,
    mesh_sha256: expectedMeshSha256,
    coordinate_units: "mm",
    field_location: "boundary_element_average",
    preview_sampled: preview.preview_sampled,
    tetrahedron_count: cellCount,
    total_boundary_triangle_count: Number(preview.total_boundary_triangle_count),
    points_mm: parsedPoints,
    triangles: parsedTriangles,
  };
}

export async function loadFemRun(runId: string, fetcher: typeof fetch = fetch): Promise<FemRunDetailData> {
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(runId)) {
    throw new Error("FEM Run ID must be a canonical UUID.");
  }
  const runResponse = await fetcher(`/api/runs/${runId}`, { cache: "no-store" });
  if (!runResponse.ok) throw new Error("Could not load the immutable FEM Run.");
  const runPayload = requireRecord(await runResponse.json(), "FEM Run response");
  const runValue = requireRecord(runPayload.run, "FEM Run record");
  if (
    runValue.id !== runId || runValue.operation !== "fdm-l2-isotropic" || runValue.status !== "succeeded" ||
    typeof runValue.created_at !== "string" || !Array.isArray(runValue.input_artifacts) ||
    !Array.isArray(runValue.output_artifacts) || !Array.isArray(runValue.stages)
  ) {
    throw new Error("The selected record is not a successful isotropic FEM Run.");
  }
  const runOutputs = runValue.output_artifacts.map((value) => requireArtifactReference(value, "Run output"));
  const stages = runValue.stages.map((value) => requireRecord(value, "Run stage"));
  if (stages.length !== 1 || stages[0].stage_id !== "fdm-l2-isotropic" || stages[0].status !== "succeeded") {
    throw new Error("The isotropic FEM Run has no successful solver stage.");
  }
  const stageOutputValues = stages[0].output_artifacts;
  if (!Array.isArray(stageOutputValues)) throw new Error("FEM stage output artifacts are missing.");
  const stageOutputs = stageOutputValues.map((value) => requireArtifactReference(value, "Stage output"));
  const resultArtifact = requireArtifactReference(runValue.result_artifact, "Result");
  if (resultArtifact.media_type !== FEM_RESULT_MEDIA_TYPE) throw new Error("FEM Run result artifact has the wrong media type.");
  const declaredResult = requireUniqueArtifact(runOutputs, FEM_RESULT_MEDIA_TYPE, "result");
  if (declaredResult.sha256 !== resultArtifact.sha256 || !stageOutputs.some((item) => item.sha256 === resultArtifact.sha256)) {
    throw new Error("FEM result artifact is not declared by the immutable Run stage.");
  }

  const resultBytes = await artifactBytes(fetcher, resultArtifact, MAX_FEM_METADATA_BYTES, "FEM result");
  const envelope = requireRecord(parseJsonBytes(resultBytes, "FEM result artifact"), "FEM result artifact") as unknown as FemResultArtifactEnvelope;
  if (
    envelope.schema_version !== 1 || envelope.run_id !== runId || envelope.stage_id !== "fdm-l2-isotropic" ||
    !isRecord(envelope.result)
  ) {
    throw new Error("FEM result artifact does not match the selected Run.");
  }
  const mesh = requireRecord(envelope.mesh, "FEM mesh metadata");
  const cellCount = mesh.cell_count;
  if (!Number.isSafeInteger(cellCount) || Number(cellCount) <= 0 || typeof mesh.sha256 !== "string" || !SHA256.test(mesh.sha256)) {
    throw new Error("FEM result mesh metadata is invalid.");
  }
  const manifest = requireRecord(envelope.artifacts, "FEM artifact manifest");
  const expectedNames = ["field-preview.json", "fields.h5", "fields.xdmf", "mesh.msh"].sort();
  if (Object.keys(manifest).sort().join("\0") !== expectedNames.join("\0")) {
    throw new Error("FEM result artifact manifest is incomplete.");
  }
  const expectedByName: Record<string, { mediaType: string; label: string }> = {
    "mesh.msh": { mediaType: "application/vnd.gmsh.msh", label: "mesh" },
    "fields.xdmf": { mediaType: "application/vnd.xdmf+xml", label: "XDMF fields" },
    "fields.h5": { mediaType: "application/x-hdf5", label: "HDF5 fields" },
    "field-preview.json": {
      mediaType: FEM_PREVIEW_MEDIA_TYPE,
      label: "declared immutable Run output field preview",
    },
  };
  const downloads: FemArtifactDownload[] = [];
  for (const [name, expected] of Object.entries(expectedByName)) {
    const manifestReference = requireArtifactReference(manifest[name], name);
    if (manifestReference.media_type !== expected.mediaType) throw new Error(`${name} has the wrong media type.`);
    const runReference = requireUniqueArtifact(runOutputs, expected.mediaType, expected.label);
    const stageReference = requireUniqueArtifact(stageOutputs, expected.mediaType, expected.label);
    if (
      manifestReference.sha256 !== runReference.sha256 || manifestReference.size_bytes !== runReference.size_bytes ||
      manifestReference.sha256 !== stageReference.sha256 || manifestReference.size_bytes !== stageReference.size_bytes
    ) {
      throw new Error(`${name} is not bound to the declared immutable Run output.`);
    }
    downloads.push({ name, ...manifestReference });
  }
  const meshManifestReference = requireArtifactReference(manifest["mesh.msh"], "mesh.msh");
  if (meshManifestReference.sha256 !== mesh.sha256) throw new Error("FEM mesh digest does not match mesh.msh.");
  const previewManifestReference = requireArtifactReference(manifest["field-preview.json"], "field-preview.json");
  const previewReference = requireUniqueArtifact(
    runOutputs,
    FEM_PREVIEW_MEDIA_TYPE,
    "declared immutable Run output field preview",
  );
  const stagePreviewReference = requireUniqueArtifact(
    stageOutputs,
    FEM_PREVIEW_MEDIA_TYPE,
    "declared immutable stage output field preview",
  );
  if (
    previewReference.sha256 !== previewManifestReference.sha256 ||
    previewReference.size_bytes !== previewManifestReference.size_bytes ||
    stagePreviewReference.sha256 !== previewReference.sha256
  ) {
    throw new Error("FEM field preview is not bound to the declared immutable Run output.");
  }
  const previewBytes = await artifactBytes(fetcher, previewReference, MAX_FEM_PREVIEW_BYTES, "FEM field preview");
  const preview = parseFemFieldPreview(previewBytes, mesh.sha256, Number(cellCount));

  const provenanceReference = requireUniqueArtifact(runOutputs, PROVENANCE_MEDIA_TYPE, "provenance");
  const stageProvenanceReference = requireUniqueArtifact(stageOutputs, PROVENANCE_MEDIA_TYPE, "provenance");
  if (provenanceReference.sha256 !== stageProvenanceReference.sha256) {
    throw new Error("Stage provenance is not declared by the Run.");
  }
  const provenanceBytes = await artifactBytes(fetcher, provenanceReference, MAX_FEM_METADATA_BYTES, "FEM provenance");
  const provenance = requireRecord(parseJsonBytes(provenanceBytes, "FEM provenance"), "FEM provenance") as unknown as FemRunProvenance;
  if (
    provenance.schema_version !== 2 || provenance.run_id !== runId ||
    provenance.image_digest !== stages[0].image_digest || provenance.git_commit !== stages[0].git_commit ||
    !SHA256.test(provenance.dependency_lock_sha256) || !SHA256.test(provenance.contract_sha256) ||
    !isRecord(provenance.runtime_versions) || !Array.isArray(provenance.inputs) || !Array.isArray(provenance.outputs)
  ) {
    throw new Error("FEM provenance does not match the immutable solver stage.");
  }
  const provenanceNames = new Set(provenance.outputs.map((item) => isRecord(item) ? item.name : undefined));
  if (expectedNames.some((name) => !provenanceNames.has(name)) || !provenanceNames.has("result.json")) {
    throw new Error("FEM provenance does not bind every solver output.");
  }
  const result = envelope.result;
  const scalarNames = [
    "reaction_force_n", "imposed_force_n", "measured_axial_displacement_mm", "nominal_stress_mpa",
    "nominal_strain", "volume_average_axial_stress_mpa", "peak_von_mises_stress_mpa",
    "axial_stress_uniformity_relative_range", "strain_energy_n_mm",
  ];
  if (scalarNames.some((name) => !finiteNumber(result[name]))) {
    throw new Error("FEM result is missing a finite scalar output.");
  }
  const typedRun = runValue as unknown as FemRunRecord;
  return {
    run: typedRun,
    envelope: envelope as unknown as FemResultEnvelope,
    preview,
    provenance,
    artifacts: [
      ...downloads,
      { name: "provenance.json", ...provenanceReference },
    ],
  };
}

export function femEvidenceLabels(
  runStatus: "succeeded" | "failed",
  verificationStatus: string,
): { execution: string; solverVerification: string; experimentalValidation: string } {
  const solverVerification = verificationStatus === "passed"
    ? "Passed for this Run"
    : verificationStatus === "failed" ? "Failed for this Run" : "Not assessed for this Run";
  return {
    execution: runStatus === "succeeded" ? "Succeeded" : "Failed",
    solverVerification,
    experimentalValidation: "Not validated against experiment",
  };
}
