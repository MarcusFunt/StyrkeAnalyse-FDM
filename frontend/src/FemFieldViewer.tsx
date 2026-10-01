import { lazy, Suspense, useCallback, useMemo, useState } from "react";
import { RotateCcw, RotateCw } from "lucide-react";
import type { FemFieldPreview } from "./lib/femRun";
import type { FemSurfaceInspection } from "./FemWebGLScene";
import {
  colorForFieldValue,
  getFieldScale,
  orderSurfaceTrianglesByDepth,
  type FemFieldKey,
} from "./lib/femViewer";

const FemWebGLScene = lazy(() => import("./FemWebGLScene"));

const fieldChoices: Array<{ key: FemFieldKey; label: string; unit: string }> = [
  { key: "von_mises_stress_mpa", label: "von Mises stress", unit: "MPa" },
  { key: "axial_stress_mpa", label: "Axial stress σₓₓ", unit: "MPa" },
  { key: "axial_displacement_mm", label: "Axial displacement uₓ", unit: "mm" },
];

interface Point2D {
  x: number;
  y: number;
}

export default function FemFieldViewer({
  preview,
  unavailableReason,
}: {
  preview: FemFieldPreview | null;
  unavailableReason: string | null;
}) {
  if (!preview) return <UnavailablePreview reason={unavailableReason} />;
  return <AvailableFieldViewer preview={preview} />;
}

function UnavailablePreview({ reason }: { reason: string | null }) {
  return (
    <section className="panel fem-viewer" aria-labelledby="fem-viewer-title">
      <div className="section-eyebrow">SOLVER FIELD</div>
      <h2 id="fem-viewer-title">Field preview unavailable</h2>
      <p role="status">{reason ?? "The solver did not provide a field preview."}</p>
      <p>Scalar results, provenance, and exact mesh and full-field downloads remain available below.</p>
    </section>
  );
}

function AvailableFieldViewer({ preview }: { preview: FemFieldPreview }) {
  const [field, setField] = useState<FemFieldKey>("von_mises_stress_mpa");
  const [yaw, setYaw] = useState(-35);
  const [showEdges, setShowEdges] = useState(true);
  const [resetRevision, setResetRevision] = useState(0);
  const [rendererMode, setRendererMode] = useState<"starting" | "webgl2" | "fallback">("starting");
  const [inspection, setInspection] = useState<FemSurfaceInspection | null>(null);
  const selected = fieldChoices.find((choice) => choice.key === field) ?? fieldChoices[0];
  const range = useMemo(
    () => getFieldScale(preview.triangles.map((triangle) => triangle[field]), field),
    [preview, field],
  );
  const onReady = useCallback(() => setRendererMode("webgl2"), []);
  const onUnavailable = useCallback(() => setRendererMode("fallback"), []);
  const colors = [
    colorForFieldValue(range.colorMinimum, field, range),
    colorForFieldValue(field === "axial_stress_mpa" ? 0 : (range.colorMinimum + range.colorMaximum) / 2, field, range),
    colorForFieldValue(range.colorMaximum, field, range),
  ];
  const legendMinimum = field === "axial_stress_mpa" ? range.colorMinimum : range.minimum;
  const legendMaximum = field === "axial_stress_mpa" ? range.colorMaximum : range.maximum;

  function resetView() {
    setYaw(-35);
    setResetRevision((revision) => revision + 1);
  }

  return (
    <section className="panel fem-viewer" aria-labelledby="fem-viewer-title">
      <div className="panel-heading fem-viewer-heading">
        <div>
          <div className="section-eyebrow">SOLVER FIELD</div>
          <h2 id="fem-viewer-title">3D mesh and field preview</h2>
          <p>Orbit the generated surface, zoom in, and inspect solver values by element.</p>
        </div>
        <div className="fem-view-controls">
          <label className="fem-field-select">Field<select aria-label="Field to visualize" value={field} onChange={(event) => { setField(event.target.value as FemFieldKey); setInspection(null); }}>{fieldChoices.map((choice) => <option key={choice.key} value={choice.key}>{choice.label}</option>)}</select></label>
          <button className="icon-button" type="button" aria-label="Rotate mesh left" onClick={() => setYaw((angle) => angle - 15)}><RotateCcw size={16} /></button>
          <button className="icon-button" type="button" aria-label="Rotate mesh right" onClick={() => setYaw((angle) => angle + 15)}><RotateCw size={16} /></button>
          <button className="fem-reset-view" type="button" onClick={resetView}>Reset view</button>
        </div>
      </div>
      <div className="fem-viewer-body">
        <div className="fem-viewer-stage">
          {rendererMode !== "fallback" && (
            <Suspense fallback={null}>
              <FemWebGLScene
                preview={preview}
                field={field}
                yaw={yaw}
                resetRevision={resetRevision}
                showEdges={showEdges}
                onReady={onReady}
                onUnavailable={onUnavailable}
                onInspection={setInspection}
              />
            </Suspense>
          )}
          {rendererMode === "fallback" && <ProjectionFallback preview={preview} field={field} showEdges={showEdges} yaw={yaw} range={range} />}
          <div className="fem-viewer-overlay-top" aria-hidden="true">
            <div className="fem-coordinate-key"><span className="axis-x">X</span> length <span className="axis-y">Y</span> width <span className="axis-z">Z</span> thickness <span className="axis-unit">mm</span></div>
            <span className={`fem-renderer-badge ${rendererMode}`}>
              <span className="fem-renderer-dot" />{rendererMode === "webgl2" ? "WEBGL2" : rendererMode === "fallback" ? "STATIC VIEW" : "STARTING"}
            </span>
          </div>
          <div className="fem-viewer-overlay-bottom" aria-hidden="true">Drag to orbit <span>·</span> scroll to zoom <span>·</span> hover a face for its value</div>
        </div>
        <div className="fem-viewer-legend">
          <div className="fem-legend-labels"><strong>{selected.label}</strong><span>{selected.unit}</span></div>
          <div className="fem-legend-gradient" style={{ background: `linear-gradient(90deg, ${colors[0]}, ${colors[1]}, ${colors[2]})` }} />
          <div className="fem-legend-range"><span>{legendMinimum.toLocaleString(undefined, { maximumSignificantDigits: 5 })}</span><span>{legendMaximum.toLocaleString(undefined, { maximumSignificantDigits: 5 })}</span></div>
          {field === "axial_stress_mpa" && <p className="fem-legend-note">Signed scale centered at 0 MPa</p>}
          <label className="fem-edge-toggle"><input type="checkbox" checked={showEdges} onChange={(event) => setShowEdges(event.target.checked)} /> Show mesh edges</label>
          {inspection && (
            <div className="fem-cell-inspection" role="status">
              <span>ELEMENT {inspection.sourceCell.toLocaleString()}</span>
              <strong>{inspection.value.toLocaleString(undefined, { maximumSignificantDigits: 6 })}<small>{selected.unit}</small></strong>
              <span>Preview cell average</span>
            </div>
          )}
          {rendererMode === "starting" && <span className="fem-renderer-starting" role="status">Starting interactive renderer…</span>}
          {rendererMode === "fallback" && <span className="fem-renderer-starting" role="status">WebGL2 unavailable · static projection shown</span>}
        </div>
      </div>
      <p className="fem-preview-caveat">Surface approximation of element averages: {preview.triangles.length.toLocaleString()} of {preview.total_boundary_triangle_count.toLocaleString()} boundary triangles{preview.preview_sampled ? ", deterministically sampled" : ""}. Display colors use the field range above; download the mesh and full volume fields for exact inspection.</p>
    </section>
  );
}

function ProjectionFallback({
  preview,
  field,
  showEdges,
  yaw,
  range,
}: {
  preview: FemFieldPreview;
  field: FemFieldKey;
  showEdges: boolean;
  yaw: number;
  range: ReturnType<typeof getFieldScale>;
}) {
  const projected = useMemo(() => {
    const angle = (yaw * Math.PI) / 180;
    const cos = Math.cos(angle);
    const sin = Math.sin(angle);
    const points: Point2D[][] = preview.triangles.map((triangle) => triangle.vertices.map((index) => {
      const [x, y, z] = preview.points_mm[index];
      const rotatedX = cos * x - sin * y;
      const rotatedY = sin * x + cos * y;
      return { x: 0.8660254 * (rotatedX - rotatedY), y: 0.5 * (rotatedX + rotatedY) - z };
    }));
    const all = points.flat();
    const minX = Math.min(...all.map((point) => point.x));
    const maxX = Math.max(...all.map((point) => point.x));
    const minY = Math.min(...all.map((point) => point.y));
    const maxY = Math.max(...all.map((point) => point.y));
    const scale = Math.min(540 / Math.max(maxX - minX, 1e-9), 350 / Math.max(maxY - minY, 1e-9));
    const offsetX = 300 - ((minX + maxX) / 2) * scale;
    const offsetY = 205 - ((minY + maxY) / 2) * scale;
    const polygons = points.map((vertices, index) => ({
      points: vertices.map((point) => `${(point.x * scale + offsetX).toFixed(2)},${(point.y * scale + offsetY).toFixed(2)}`).join(" "),
      value: preview.triangles[index][field],
      index,
    }));
    return orderSurfaceTrianglesByDepth(preview, yaw).map((index) => polygons[index]);
  }, [preview, field, yaw]);

  return (
    <svg className="fem-mesh-svg" viewBox="0 0 600 410" role="img" aria-label={`${fieldChoices.find((choice) => choice.key === field)?.label ?? field} 3D field projection over ${projected.length.toLocaleString()} boundary triangles`}>
      <defs><radialGradient id="fem-stage-glow"><stop offset="0" stopColor="#1e3e4c" /><stop offset="1" stopColor="#101f2a" /></radialGradient></defs>
      <rect x="0" y="0" width="600" height="410" rx="10" fill="url(#fem-stage-glow)" />
      {projected.map((polygon) => <polygon key={polygon.index} points={polygon.points} fill={colorForFieldValue(polygon.value, field, range)} stroke={showEdges ? "#b8cbd4" : "none"} strokeOpacity="0.47" strokeWidth={showEdges ? "0.65" : "0"} strokeLinejoin="round" />)}
    </svg>
  );
}
