import { useState, type FormEvent } from "react";
import { Box, CheckCircle2, CircleAlert, LoaderCircle, Play, ShieldCheck } from "lucide-react";
import {
  buildIsotropicTensileRequest,
  type FemFormValues,
  type FemJobStatus,
  type IsotropicTensileRequest,
} from "./lib/fem";
import type { FemRunDetailData } from "./lib/femRun";
import { D638_PRESETS, type FemSpecimenShape } from "./lib/specimenPresets";
import FemRunDetail from "./FemRunDetail";

const initialValues: FemFormValues = {
  specimenId: "FEM-T01",
  specimenShape: "rectangular",
  lengthMm: "50",
  widthMm: "10",
  thicknessMm: "2",
  materialProfileId: "PLA-isotropic-v1",
  youngsModulusMpa: "2000",
  poissonsRatio: "0.35",
  forceN: "100",
  maxCellSizeMm: "5",
  elementOrder: 1,
  optimize: true,
};

interface FemPageProps {
  apiReady: boolean;
  status: FemJobStatus;
  error: string;
  runId: string | null;
  detail: FemRunDetailData | null;
  detailError: string;
  loadingDetail: boolean;
  onSubmit: (request: IsotropicTensileRequest) => Promise<void>;
}

const statusText: Record<FemJobStatus, string> = {
  idle: "Ready to submit",
  preparing: "Preparing solve",
  queued: "Queued",
  running: "Solver running",
  succeeded: "Run succeeded",
  failed: "Run failed",
};

export default function FemPage(props: FemPageProps) {
  const [values, setValues] = useState(initialValues);
  const [formError, setFormError] = useState("");
  const busy = props.status === "preparing" || props.status === "queued" || props.status === "running" || props.loadingDetail;
  const d638Preset = values.specimenShape === "rectangular" ? null : D638_PRESETS[values.specimenShape];
  const submitLabel = props.status === "preparing"
    ? "Preparing solve…"
    : props.loadingDetail ? "Loading results…" : "Submit FEM solve";

  function set<K extends keyof FemFormValues>(key: K, value: FemFormValues[K]): void {
    setValues((current) => ({ ...current, [key]: value }));
    setFormError("");
  }

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setFormError("");
    try {
      await props.onSubmit(buildIsotropicTensileRequest(values));
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "The FEM request could not be prepared.");
    }
  }

  return (
    <div className="fem-workspace">
      <section className="fem-intro">
        <div>
          <div className="section-eyebrow">FORMAL SOLVER STAGE · FDM-L2-ISOTROPIC</div>
          <h2>{d638Preset ? d638Preset.label : "Rectangular tensile specimen"}</h2>
          <p>{d638Preset
            ? "Solve the checked full dog-bone outline with an end-face traction load. The nominal standard geometry is sealed into the Run."
            : "Set the specimen, material, axial load and mesh. The request is sealed as an immutable Run input."}</p>
        </div>
        <span className="fem-stage-badge"><ShieldCheck size={15} /> Server controlled stage</span>
      </section>

      <div className="fem-layout">
        <form className="panel fem-form" onSubmit={(event) => void submit(event)}>
          <fieldset disabled={busy || !props.apiReady}>
            <legend>Specimen geometry</legend>
            <div className="fem-form-grid">
              <label className="fem-field fem-field-wide" htmlFor="fem-specimen-shape">
                Geometry
                <select id="fem-specimen-shape" value={values.specimenShape} onChange={(event) => {
                  const shape = event.target.value as FemSpecimenShape;
                  set("specimenShape", shape);
                  if (shape !== "rectangular") set("thicknessMm", String(D638_PRESETS[shape].nominalThicknessMm));
                }}>
                  <option value="rectangular">Rectangular verification coupon</option>
                  <option value="I">ASTM D638 Type I</option>
                  <option value="IV">ASTM D638 Type IV</option>
                  <option value="V">ASTM D638 Type V</option>
                </select>
              </label>
              <label className="fem-field fem-field-wide" htmlFor="fem-specimen-id">
                Specimen ID
                <input id="fem-specimen-id" value={values.specimenId} onChange={(event) => set("specimenId", event.target.value)} maxLength={128} required />
              </label>
              {d638Preset ? (
                <>
                  <FemNumberField id="fem-thickness" label="Measured thickness" unit="mm" value={values.thicknessMm} onChange={(value) => set("thicknessMm", value)} min="0.000001" max="100" />
                  <div className="d638-preset-summary fem-field-wide" role="note">
                    <strong>{d638Preset.standardRevision} · Type {d638Preset.type}</strong>
                    <span>LO {d638Preset.overallLengthMm} mm · WO {d638Preset.overallWidthMm} mm · W {d638Preset.gaugeWidthMm} mm · L {d638Preset.narrowLengthMm} mm · G {d638Preset.gaugeLengthMm} mm · D {d638Preset.gripSeparationMm} mm</span>
                    <span>R {d638Preset.innerRadiusMm} mm{d638Preset.outerRadiusMm ? ` · RO ${d638Preset.outerRadiusMm} mm` : ""} · nominal CAD T {d638Preset.nominalThicknessMm} mm</span>
                  </div>
                </>
              ) : (
                <>
                  <FemNumberField id="fem-length" label="Length" unit="mm" value={values.lengthMm} onChange={(value) => set("lengthMm", value)} min="0.000001" max="1000" />
                  <FemNumberField id="fem-width" label="Width" unit="mm" value={values.widthMm} onChange={(value) => set("widthMm", value)} min="0.000001" max="500" />
                  <FemNumberField id="fem-thickness" label="Thickness" unit="mm" value={values.thicknessMm} onChange={(value) => set("thicknessMm", value)} min="0.000001" max="100" />
                </>
              )}
            </div>
            {d638Preset && <p className="fem-form-note">The outline is generated from the checked rig-reference dimensions. Replace 3.2 mm with the measured printed thickness when analysing a physical coupon. D is a grip-separation setup dimension, not the start of the rectangular tab.</p>}
          </fieldset>

          <fieldset disabled={busy || !props.apiReady}>
            <legend>Isotropic material and load</legend>
            <div className="fem-form-grid">
              <label className="fem-field fem-field-wide" htmlFor="fem-profile-id">
                Material profile ID
                <input id="fem-profile-id" value={values.materialProfileId} onChange={(event) => set("materialProfileId", event.target.value)} maxLength={128} required />
              </label>
              <FemNumberField id="fem-modulus" label="Young’s modulus" unit="MPa" value={values.youngsModulusMpa} onChange={(value) => set("youngsModulusMpa", value)} min="0.000001" max="1000000" />
              <FemNumberField id="fem-poisson" label="Poisson’s ratio" unit="ν" value={values.poissonsRatio} onChange={(value) => set("poissonsRatio", value)} min="-0.999999" max="0.499999" />
              <FemNumberField id="fem-force" label="Axial force" unit="N" value={values.forceN} onChange={(value) => set("forceN", value)} min="0.000001" max="1000000000" />
            </div>
            <p className="fem-form-note">Small-strain, linear-elastic isotropic response. {d638Preset ? "The requested force is converted to a uniform traction over the full loaded end face." : "The rectangular verification case uses the existing prescribed-displacement equivalent of the requested force."}</p>
          </fieldset>

          <fieldset disabled={busy || !props.apiReady}>
            <legend>Mesh and element order</legend>
            <div className="fem-form-grid">
              <FemNumberField id="fem-cell-size" label="Maximum cell size" unit="mm" value={values.maxCellSizeMm} onChange={(value) => set("maxCellSizeMm", value)} min="0.000001" max="100" />
              <label className="fem-field" htmlFor="fem-element-order">
                Element order
                <select id="fem-element-order" value={values.elementOrder} onChange={(event) => set("elementOrder", Number(event.target.value) as 1 | 2)}>
                  <option value={1}>P1 · linear tetrahedra</option>
                  <option value={2}>P2 · quadratic tetrahedra</option>
                </select>
              </label>
              <label className="fem-checkbox" htmlFor="fem-optimize">
                <input id="fem-optimize" type="checkbox" checked={values.optimize} onChange={(event) => set("optimize", event.target.checked)} />
                <span>Optimize higher-order mesh</span>
              </label>
            </div>
          </fieldset>

          {!props.apiReady && <div className="fem-inline-note" role="status"><CircleAlert size={15} /> Connect to the local analysis service before submitting a solve.</div>}
          {(formError || props.error) && <div className="fem-error" role="alert"><CircleAlert size={16} /><span>{formError || props.error}</span></div>}
          <div className="fem-submit-row">
            <span>Gmsh mesh · DOLFINx elasticity · isolated runner</span>
            <button className="button button-primary" type="submit" disabled={busy || !props.apiReady}>
              {busy ? <LoaderCircle className="fem-spinner" size={16} /> : <Play size={15} />}
              {submitLabel}
            </button>
          </div>
        </form>

        <aside className="fem-side-column">
          <section className="panel fem-job-card" aria-labelledby="fem-job-title">
            <div className="section-eyebrow">ASYNC JOB</div>
            <h3 id="fem-job-title">Solver job status</h3>
            <div className={`fem-status ${props.status}`} role={props.status === "failed" ? "alert" : "status"}>
              {props.status === "succeeded" ? <CheckCircle2 size={17} /> : props.status === "failed" ? <CircleAlert size={17} /> : busy ? <LoaderCircle className="fem-spinner" size={17} /> : <Box size={17} />}
              <span>{statusText[props.status]}</span>
            </div>
            <p>{busy ? "The persistent job is running outside the browser request; this page is polling its saved status." : "The runner owns the image, command, CPU and memory limits."}</p>
            {props.runId && <div className="fem-run-id"><span>Immutable Run ID</span><code>{props.runId}</code></div>}
          </section>
          <section className="fem-state-note">
            <div className="state-note-icon"><ShieldCheck size={17} /></div>
            <div><strong>Evidence stays separate</strong><p>Run success means the solve completed. M4 solver verification and comparison with experiments are reported as separate states.</p></div>
          </section>
        </aside>
      </div>

      {props.runId && props.loadingDetail && <div className="fem-detail-loading" role="status"><LoaderCircle className="fem-spinner" size={17} /> Loading the immutable mesh, fields and provenance…</div>}
      {props.runId && props.detailError && <div className="fem-error fem-detail-error" role="alert"><CircleAlert size={16} /><span>{props.detailError}</span></div>}
      {props.detail && <FemRunDetail detail={props.detail} />}
    </div>
  );
}

function FemNumberField(props: {
  id: string;
  label: string;
  unit: string;
  value: string;
  min: string;
  max: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="fem-field" htmlFor={props.id}>
      {props.label}
      <div className="fem-number-input">
        <input id={props.id} type="number" step="any" min={props.min} max={props.max} value={props.value} onChange={(event) => props.onChange(event.target.value)} required />
        <span>{props.unit}</span>
      </div>
    </label>
  );
}
