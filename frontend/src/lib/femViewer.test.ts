import { describe, expect, it } from "vitest";
import {
  isNumericallyUniform,
  orderSurfaceTrianglesByDepth,
} from "./femViewer";
import type { FemFieldPreview } from "./femRun";

function overlappingPreview(yaw: number): FemFieldPreview {
  const radians = (yaw * Math.PI) / 180;
  const cos = Math.cos(radians);
  const sin = Math.sin(radians);
  const shiftX = 2 * cos + 2 * sin;
  const shiftY = -2 * sin + 2 * cos;
  const far: [number, number, number][] = [[0, 0, 0], [1, 0, 0], [0, 1, 0]];
  const near: [number, number, number][] = far.map(([x, y, z]) => [
    x + shiftX,
    y + shiftY,
    z + 2,
  ]);
  const triangle = (vertices: [number, number, number], value: number) => ({
    vertices,
    source_cell: 0,
    von_mises_stress_mpa: value,
    axial_stress_mpa: value,
    axial_displacement_mm: value,
  });
  return {
    schema_version: 1,
    mesh_sha256: "a".repeat(64),
    coordinate_units: "mm",
    field_location: "boundary_element_average",
    preview_sampled: false,
    tetrahedron_count: 2,
    total_boundary_triangle_count: 2,
    points_mm: [...far, ...near],
    triangles: [
      triangle([0, 1, 2], 1),
      triangle([3, 4, 5], 2),
    ],
  };
}

describe("FEM field preview rendering geometry", () => {
  it("paints a nearer overlapping triangle after the hidden triangle at each yaw", () => {
    for (const yaw of [-35, -20, 10, 55]) {
      expect(orderSurfaceTrianglesByDepth(overlappingPreview(yaw), yaw)).toEqual([0, 1]);
    }
  });

  it("treats floating-point noise as a uniform field while preserving real variation", () => {
    expect(isNumericallyUniform(5, 5 + 3.38e-13)).toBe(true);
    expect(isNumericallyUniform(5, 5.001)).toBe(false);
  });
});
