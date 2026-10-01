import type { FemFieldPreview } from "./femRun";

export type FemFieldKey = "von_mises_stress_mpa" | "axial_stress_mpa" | "axial_displacement_mm";

export interface FemFieldScale {
  minimum: number;
  maximum: number;
  colorMinimum: number;
  colorMaximum: number;
  uniform: boolean;
}

export interface FemFieldMeshData {
  /** Centered, aspect-preserving XYZ positions scaled so the longest side is four scene units. */
  positions: Float32Array;
  /** One value for each source boundary triangle. */
  triangleValues: Float64Array;
  /** Original volume-mesh cell for each preview triangle. */
  sourceCells: Uint32Array;
  range: FemFieldScale;
}

const SEQUENTIAL_STOPS = ["#2a6f9e", "#35ad9d", "#f6c055", "#c5493a"];
const DIVERGING_STOPS = ["#397ca5", "#f4f1e7", "#bb493d"];

export function orderSurfaceTrianglesByDepth(preview: FemFieldPreview, yawDegrees: number): number[] {
  const radians = (yawDegrees * Math.PI) / 180;
  const cos = Math.cos(radians);
  const sin = Math.sin(radians);
  return preview.triangles
    .map((triangle, index) => {
      const depth = triangle.vertices.reduce((total, pointIndex) => {
        const [x, y, z] = preview.points_mm[pointIndex];
        const rotatedX = cos * x - sin * y;
        const rotatedY = sin * x + cos * y;
        return total + rotatedX + rotatedY + z;
      }, 0) / triangle.vertices.length;
      return { index, depth };
    })
    .sort((left, right) => left.depth - right.depth || left.index - right.index)
    .map(({ index }) => index);
}

export function isNumericallyUniform(minimum: number, maximum: number): boolean {
  const scale = Math.max(Math.abs(minimum), Math.abs(maximum));
  return maximum - minimum <= Math.max(1e-12, scale * 1e-10);
}

export function getFieldScale(values: number[], field: FemFieldKey): FemFieldScale {
  if (!values.length) throw new Error("A FEM field preview must contain at least one field value.");
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  const uniform = isNumericallyUniform(minimum, maximum);
  if (field === "axial_stress_mpa") {
    const extent = Math.max(Math.abs(minimum), Math.abs(maximum));
    return { minimum, maximum, colorMinimum: -extent, colorMaximum: extent, uniform };
  }
  return { minimum, maximum, colorMinimum: minimum, colorMaximum: maximum, uniform };
}

export function buildFieldMeshData(preview: FemFieldPreview, field: FemFieldKey): FemFieldMeshData {
  const values = preview.triangles.map((triangle) => triangle[field]);
  const range = getFieldScale(values, field);
  const bounds = [0, 1, 2].map((axis) => ({
    minimum: Math.min(...preview.points_mm.map((point) => point[axis])),
    maximum: Math.max(...preview.points_mm.map((point) => point[axis])),
  }));
  const center = bounds.map(({ minimum, maximum }) => (minimum + maximum) / 2);
  const extent = Math.max(...bounds.map(({ minimum, maximum }) => maximum - minimum));
  const scale = extent > 0 ? 4 / extent : 1;
  const positions = new Float32Array(preview.triangles.length * 9);
  preview.triangles.forEach((triangle, triangleIndex) => {
    triangle.vertices.forEach((pointIndex, vertexIndex) => {
      const point = preview.points_mm[pointIndex];
      const offset = triangleIndex * 9 + vertexIndex * 3;
      positions[offset] = (point[0] - center[0]) * scale;
      positions[offset + 1] = (point[1] - center[1]) * scale;
      positions[offset + 2] = (point[2] - center[2]) * scale;
    });
  });
  return {
    positions,
    triangleValues: Float64Array.from(values),
    sourceCells: Uint32Array.from(preview.triangles.map((triangle) => triangle.source_cell)),
    range,
  };
}

export function colorForFieldValue(value: number, field: FemFieldKey, range: FemFieldScale): string {
  if (range.uniform && field !== "axial_stress_mpa") return "#78999c";
  if (field === "axial_stress_mpa") {
    if (range.colorMaximum === 0) return DIVERGING_STOPS[1];
    const fraction = Math.max(0, Math.min(1, (value - range.colorMinimum) / (range.colorMaximum - range.colorMinimum)));
    return interpolateStops(DIVERGING_STOPS, fraction);
  }
  if (range.uniform) return "#78999c";
  const fraction = Math.max(0, Math.min(1, (value - range.colorMinimum) / (range.colorMaximum - range.colorMinimum)));
  return interpolateStops(SEQUENTIAL_STOPS, fraction);
}

function interpolateStops(stops: string[], fraction: number): string {
  const position = fraction * (stops.length - 1);
  const index = Math.min(Math.floor(position), stops.length - 2);
  const ratio = position - index;
  const left = parseHex(stops[index]);
  const right = parseHex(stops[index + 1]);
  return `#${left.map((channel, channelIndex) => Math.round(channel + (right[channelIndex] - channel) * ratio).toString(16).padStart(2, "0")).join("")}`;
}

function parseHex(color: string): number[] {
  return [1, 3, 5].map((index) => Number.parseInt(color.slice(index, index + 2), 16));
}
