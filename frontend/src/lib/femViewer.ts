import type { FemFieldPreview } from "./femRun";

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
