import { ArrowDownToLine, Box, CheckCircle2, CircleAlert, FileBox, Fingerprint, ShieldCheck } from "lucide-react";
import { femEvidenceLabels, type FemRunDetailData } from "./lib/femRun";
import FemFieldViewer from "./FemFieldViewer";

const scalarDefinitions: Array<{ key: string; label: string; unit: string; digits: number }> = [
  { key: "reaction_force_n", label: "Reaction force", unit: "N", digits: 3 },
  { key: "imposed_force_n", label: "Applied force", unit: "N", digits: 3 },
  { key: "measured_axial_displacement_mm", label: "Axial displacement", unit: "mm", digits: 5 },
  { key: "nominal_stress_mpa", label: "Nominal stress", unit: "MPa", digits: 4 },
  { key: "nominal_strain", label: "Nominal strain", unit: "mm/mm", digits: 6 },
  { key: "volume_average_axial_stress_mpa", label: "Volume average σₓₓ", unit: "MPa", digits: 4 },
  { key: "peak_von_mises_stress_mpa", label: "Peak von Mises stress", unit: "MPa", digits: 4 },
  { key: "axial_stress_uniformity_relative_range", label: "Axial stress variation", unit: "relative", digits: 5 },
  { key: "strain_energy_n_mm", label: "Strain energy", unit: "N·mm", digits: 5 },
];

function pretty(value: unknown): string {
  if (typeof value === "number") return value.toLocaleString(undefined, { maximumSignificantDigits: 7 });
  if (typeof value === "string") return value;
  if (value === null || value === undefined) return "Not recorded";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return JSON.stringify(value);
}

function MetadataGrid({ title, eyebrow, values }: { title: string; eyebrow: string; values: Array<[string, unknown]> }) {
  return (
    <section className="fem-metadata-section">
      <div className="section-eyebrow">{eyebrow}</div>
      <h3>{title}</h3>
      <dl className="fem-metadata-grid">
        {values.map(([label, value]) => <div className="fem-metadata-item" key={label}><dt>{label}</dt><dd title={pretty(value)}>{pretty(value)}</dd></div>)}
      </dl>
    </section>
  );
}

export default function FemRunDetail({ detail }: { detail: FemRunDetailData }) {
  const { run, envelope, provenance } = detail;
  const evidence = femEvidenceLabels(run.status, envelope.verification_status);
  const specimen = envelope.specimen;
  const material = envelope.material;
  const boundaryConditions = envelope.boundary_conditions;
  const mesh = envelope.mesh;
  const solver = envelope.solver_metadata;
  const stage = run.stages[0];

  return (
    <div className="fem-run-detail" aria-labelledby="fem-result-title">
      <section className="fem-run-heading">
        <div><div className="section-eyebrow">IMMUTABLE FEM RUN</div><h2 id="fem-result-title">Solve results and evidence</h2><p>Completed {new Date(run.created_at).toLocaleString()} · Run <code>{run.id}</code></p></div>
        <a className="text-button" href={`/api/runs/${run.id}`} target="_blank" rel="noreferrer">Open Run record</a>
      </section>

      <section className="fem-evidence-grid" aria-label="Scientific evidence status">
        <EvidenceCard icon={<CheckCircle2 size={16} />} label="Execution" value={evidence.execution} tone="complete" detail="The immutable solver stage completed successfully." />
        <EvidenceCard icon={<ShieldCheck size={16} />} label="Solver verification" value={evidence.solverVerification} tone="pending" detail="M4 verification is assessed by its separate verification suite." />
        <EvidenceCard icon={<CircleAlert size={16} />} label="Experimental validation" value={evidence.experimentalValidation} tone="pending" detail="No physical measurement has been used to validate this model." />
      </section>

      <section className="fem-result-metrics" aria-label="Scalar FEM results">
        {scalarDefinitions.map(({ key, label, unit, digits }) => {
          const value = envelope.result[key];
          return <article className="fem-scalar-card" key={key}><span>{label}</span><strong>{value.toLocaleString(undefined, { maximumFractionDigits: digits })}<small>{unit}</small></strong></article>;
        })}
      </section>

      <FemFieldViewer preview={detail.preview} unavailableReason={detail.previewError} />

      <section className="panel fem-artifacts-panel">
        <div className="panel-heading"><div><div className="section-eyebrow">CONTENT ADDRESSED OUTPUTS</div><h2>Mesh, fields and provenance files</h2><p>Each link retrieves the exact bytes identified by the immutable SHA-256 digest.</p></div><FileBox size={18} /></div>
        <div className="fem-artifact-list">
          {detail.artifacts.map((artifact) => <a className="fem-artifact-row" key={artifact.name} href={`/api/artifacts/${artifact.sha256}`} download={artifact.name}>
            <span className="fem-artifact-icon"><Box size={15} /></span>
            <span className="fem-artifact-name"><strong>{artifact.name}</strong><code>{artifact.sha256}</code></span>
            <span className="fem-artifact-size">{artifact.size_bytes.toLocaleString()} bytes</span>
            <ArrowDownToLine size={15} aria-hidden="true" />
          </a>)}
        </div>
      </section>

      <section className="panel fem-provenance-panel">
        <div className="panel-heading"><div><div className="section-eyebrow">REPRODUCIBILITY</div><h2>Solver inputs and provenance</h2><p>Recorded with the sealed Run and server-controlled stage image.</p></div><Fingerprint size={18} /></div>
        <div className="fem-metadata-columns">
          <MetadataGrid eyebrow="SPECIMEN" title={pretty(specimen.specimen_id)} values={[
            ["Length", `${pretty(specimen.length_mm)} mm`], ["Width", `${pretty(specimen.width_mm)} mm`], ["Thickness", `${pretty(specimen.thickness_mm)} mm`],
          ]} />
          <MetadataGrid eyebrow="MATERIAL" title={pretty(material.profile_id)} values={[
            ["Young’s modulus", `${pretty(material.youngs_modulus_mpa)} MPa`], ["Poisson’s ratio", pretty(material.poissons_ratio)], ["Material SHA-256", material.sha256],
          ]} />
          <MetadataGrid eyebrow="BOUNDARY CONDITIONS" title={pretty(boundaryConditions.set_id)} values={Object.entries(boundaryConditions)} />
          <MetadataGrid eyebrow="MESH SETTINGS" title={`${pretty(mesh.element_order)}-order tetrahedra`} values={[
            ["Maximum cell size", `${pretty(mesh.max_cell_size_mm)} mm`], ["Cells", mesh.cell_count], ["Mesh SHA-256", mesh.sha256],
          ]} />
          <MetadataGrid eyebrow="SOLVER" title={`${pretty(solver.name)} ${pretty(solver.version)}`} values={[
            ["Iterations", solver.iteration_count], ["Residual norm", solver.residual_norm], ["MPI ranks", solver.mpi_ranks], ["OMP threads", solver.omp_threads], ["BLAS threads", solver.blas_threads], ["Allocated CPUs", solver.allocated_cpus], ["Elapsed", `${pretty(solver.elapsed_seconds)} s`],
          ]} />
          <MetadataGrid eyebrow="EXECUTION IMAGE" title={provenance.image_reference} values={[
            ["Image digest", provenance.image_digest], ["Base image", provenance.base_image_reference], ["Source commit", provenance.git_commit], ["Source dirty", provenance.git_dirty], ["Dependency lock SHA-256", provenance.dependency_lock_sha256], ["Run contract SHA-256", provenance.contract_sha256], ["Stage duration", `${pretty(stage.duration_ms)} ms`], ["Memory limit", `${pretty(stage.memory_limit_bytes)} bytes`],
          ]} />
          <MetadataGrid eyebrow="RUNTIME VERSIONS" title="Solver environment" values={Object.entries(provenance.runtime_versions)} />
        </div>
      </section>
    </div>
  );
}

function EvidenceCard(props: { icon: React.ReactNode; label: string; value: string; tone: "complete" | "pending"; detail: string }) {
  return <article className={`fem-evidence-card ${props.tone}`}><span className="fem-evidence-icon">{props.icon}</span><div><span>{props.label}</span><strong>{props.value}</strong><p>{props.detail}</p></div></article>;
}
