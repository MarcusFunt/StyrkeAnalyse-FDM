import Papa from "papaparse";

export type CsvRow = Record<string, string>;

export interface ParsedCsv {
  columns: string[];
  rows: CsvRow[];
  warnings: string[];
}

export function parseCsvText(source: string): ParsedCsv {
  if (!source.trim()) {
    throw new Error("The file is empty. It needs a header row and measurement rows.");
  }
  const parsed = Papa.parse<string[]>(source, {
    header: false,
    skipEmptyLines: "greedy",
    dynamicTyping: false,
  });
  const [rawHeader, ...dataRows] = parsed.data;
  if (!rawHeader?.length) {
    throw new Error("Could not find a header row. Add column names to the first row.");
  }
  const columns = rawHeader.map((field) => field.trim());
  if (columns.some((column) => !column)) {
    throw new Error("An empty header is invalid. Name every column in the first row.");
  }
  const seen = new Set<string>();
  for (const column of columns) {
    if (seen.has(column)) {
      throw new Error(`Duplicate CSV header after trimming: ${column}`);
    }
    seen.add(column);
  }
  const extraFieldIndex = dataRows.findIndex((values) => values.length > columns.length);
  if (extraFieldIndex >= 0) {
    throw new Error(`A data row has more values than the CSV header (near row ${extraFieldIndex + 2}). Check the delimiter and header columns.`);
  }
  const rows = dataRows
    .filter((values) => values.some((value) => String(value ?? "").trim() !== ""))
    .map((values) =>
      Object.fromEntries(columns.map((column, index) => [column, values[index] ?? ""])),
    );
  if (rows.length === 0) {
    throw new Error("The file has headers but no measurement rows.");
  }
  return {
    columns,
    rows,
    warnings: parsed.errors.map((error) => {
      const row = typeof error.row === "number" ? ` (row ${error.row + 1})` : "";
      return `${error.message}${row}`;
    }),
  };
}
