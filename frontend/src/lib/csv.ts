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
  const parsed = Papa.parse<CsvRow>(source, {
    header: true,
    skipEmptyLines: "greedy",
    dynamicTyping: false,
  });
  const columns = (parsed.meta.fields ?? []).map((field) => field.trim()).filter(Boolean);
  if (columns.length === 0) {
    throw new Error("Could not find a header row. Add column names to the first row.");
  }
  const rows = parsed.data.filter((row) =>
    Object.values(row).some((value) => String(value ?? "").trim() !== ""),
  );
  if (rows.length === 0) {
    throw new Error("The file has headers but no measurement rows.");
  }
  return {
    columns,
    rows,
    warnings: parsed.errors.map((error) => {
      const row = typeof error.row === "number" ? ` (row ${error.row + 2})` : "";
      return `${error.message}${row}`;
    }),
  };
}
