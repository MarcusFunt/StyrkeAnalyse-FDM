export function guessColumn(columns: string[], pattern: RegExp): string {
  const matches = columns.filter((column) => {
    pattern.lastIndex = 0;
    return pattern.test(column);
  });
  return matches.length === 1 ? matches[0] : "";
}

export function isAnalysisInputValid(
  columns: string[],
  forceColumn: string,
  displacementColumn: string,
  widthMm: string,
  thicknessMm: string,
  gaugeLengthMm: string,
): boolean {
  const dimensions = [widthMm, thicknessMm, gaugeLengthMm].map(Number);
  return (
    areColumnsMapped(columns, forceColumn, displacementColumn) &&
    dimensions.every((dimension) => Number.isFinite(dimension) && dimension > 0)
  );
}

export function areColumnsMapped(columns: string[], forceColumn: string, displacementColumn: string): boolean {
  return (
    forceColumn !== displacementColumn &&
    columns.includes(forceColumn) &&
    columns.includes(displacementColumn)
  );
}

export function areDimensionsValid(widthMm: string, thicknessMm: string, gaugeLengthMm: string): boolean {
  return [widthMm, thicknessMm, gaugeLengthMm]
    .map(Number)
    .every((dimension) => Number.isFinite(dimension) && dimension > 0);
}

export function analysisInputFingerprint(value: {
  rows: unknown;
  columns: string[];
  settings: unknown;
  inputSha256: string | null;
  specimenId: string;
  reductionMetadata?: unknown;
}): string {
  return JSON.stringify(value);
}

export function isAnalysisSnapshotCurrent(submitted: string, current: string): boolean {
  return submitted === current;
}
