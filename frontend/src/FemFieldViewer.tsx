import { useMemo, useState } from "react";
import { RotateCcw, RotateCw } from "lucide-react";
import type { FemFieldPreview } from "./lib/femRun";

type FieldKey = "von_mises_stress_mpa" | "axial_stress_mpa" | "axial_displacement_mm";

const fieldChoices: Array<{ key: FieldKey; label: string; unit: string }> = [
  { key: "von_mises_stress_mpa", label: "von Mises stress", unit: "MPa" },
  { key: "axial_stress_mpa", label: "Axial stress σₓₓ", unit: "MPa" },
  { key: "axial_displacement_mm", label: "Axial displacement uₓ", unit: "mm" },
];

interface Point2D {
  x: number;
  y: number;
}

export default function FemFieldViewer({ preview }: { preview: FemFieldPreview }) {
  const [field, setField] = useState<FieldKey>("von_mises_stress_mpa");
  const [yaw, setYaw] = useState(-35);
  const [showEdges, setShowEdges] = useState(true);
  const selected = fieldChoices.find((choice) => choice.key === field) ?? fieldChoices[0];
  const values = preview.triangles.map((triangle) => triangle[field]);
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  const range = maximum - minimum;

  const polygons = useMemo(() => {
    const angle = (yaw * Math.PI) / 180;
    const cos = Math.cos(angle);
    const sin = Math.sin(angle);
    const projected: Point2D[][] = preview.triangles.map((triangle) => triangle.vertices.map((index) => {
      const [x, y, z] = preview.points_mm[index];
      const rotatedX = cos * x - sin * y;
      const rotatedY = sin * x + cos * y;
      return { x: 0.8660254 * (rotatedX - rotatedY), y: 0.5 * (rotatedX + rotatedY) - z };
    }));
    const all = projected.flat();
    const minX = Math.min(...all.map((point) => point.x));
    const maxX = Math.max(...all.map((point) => point.x));
    const minY = Math.min(...all.map((point) => point.y));
    const maxY = Math.max(...all.map((point) => point.y));
    const scale = Math.min(540 / Math.max(maxX - minX, 1e-9), 350 / Math.max(maxY - minY, 1e-9));
    const offsetX = 300 - ((minX + maxX) / 2) * scale;
    const offsetY = 205 - ((minY + maxY) / 2) * scale;
    return projected.map((points, index) => ({
      points: points.map((point) => `${(point.x * scale + offsetX).toFixed(2)},${(point.y * scale + offsetY).toFixed(2)}`).join(" "),
      value: values[index],
      index,
    }));
  }, [preview, values, yaw]);

  function color(value: number): string {
    const fraction = range <= Number.EPSILON ? 0.5 : Math.max(0, Math.min(1, (value - minimum) / range));
    if (field === "axial_stress_mpa") {
      if (fraction < 0.5) {
        const t = fraction * 2;
        return `rgb(${Math.round(48 + 202 * t)},${Math.round(100 + 144 * t)},${Math.round(177 + 65 * t)})`;
      }
      const t = (fraction - 0.5) * 2;
      return `rgb(250,${Math.round(244 - 120 * t)},${Math.round(242 - 115 * t)})`;
    }
    const stops = [[42, 111, 158], [53, 173, 157], [246, 192, 85], [197, 73, 58]];
    const position = fraction * (stops.length - 1);
    const left = Math.floor(position);
    const mix = position - left;
    const a = stops[left];
    const b = stops[Math.min(left + 1, stops.length - 1)];
    return `rgb(${a.map((channel, index) => Math.round(channel + (b[index] - channel) * mix)).join(",")})`;
  }

  return (
    <section className="panel fem-viewer" aria-labelledby="fem-viewer-title">
      <div className="panel-heading fem-viewer-heading">
        <div><div className="section-eyebrow">SOLVER FIELD</div><h2 id="fem-viewer-title">Surface mesh and field preview</h2><p>One averaged field value per boundary triangle.</p></div>
        <div className="fem-view-controls">
          <label className="fem-field-select">Field<select aria-label="Field to visualize" value={field} onChange={(event) => setField(event.target.value as FieldKey)}>{fieldChoices.map((choice) => <option key={choice.key} value={choice.key}>{choice.label}</option>)}</select></label>
          <button className="icon-button" type="button" aria-label="Rotate mesh left" onClick={() => setYaw((angle) => angle - 15)}><RotateCcw size={16} /></button>
          <button className="icon-button" type="button" aria-label="Rotate mesh right" onClick={() => setYaw((angle) => angle + 15)}><RotateCw size={16} /></button>
        </div>
      </div>
      <div className="fem-viewer-body">
        <svg className="fem-mesh-svg" viewBox="0 0 600 410" role="img" aria-label={`${selected.label} surface field over ${polygons.length.toLocaleString()} boundary triangles`}>
          <defs><linearGradient id="fem-field-legend" x1="0" x2="1"><stop offset="0%" stopColor={color(minimum)} /><stop offset="100%" stopColor={color(maximum)} /></linearGradient></defs>
          <rect x="0" y="0" width="600" height="410" rx="10" fill="#f7faf9" />
          {polygons.map((polygon) => <polygon key={polygon.index} points={polygon.points} fill={color(polygon.value)} stroke={showEdges ? "#263f4a" : "none"} strokeWidth={showEdges ? "0.65" : "0"} strokeLinejoin="round" />)}
        </svg>
        <div className="fem-viewer-legend">
          <div className="fem-legend-labels"><strong>{selected.label}</strong><span>{selected.unit}</span></div>
          <div className="fem-legend-gradient" />
          <div className="fem-legend-range"><span>{minimum.toLocaleString(undefined, { maximumSignificantDigits: 5 })}</span><span>{maximum.toLocaleString(undefined, { maximumSignificantDigits: 5 })}</span></div>
          <label className="fem-edge-toggle"><input type="checkbox" checked={showEdges} onChange={(event) => setShowEdges(event.target.checked)} /> Show mesh edges</label>
        </div>
      </div>
      <p className="fem-preview-caveat">This is a surface approximation of element averages ({preview.triangles.length.toLocaleString()} of {preview.total_boundary_triangle_count.toLocaleString()} boundary triangles{preview.preview_sampled ? ", deterministically sampled" : ""}). Download the mesh and full volume fields for exact inspection.</p>
    </section>
  );
}
