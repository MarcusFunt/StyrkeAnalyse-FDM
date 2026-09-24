import type { CsvRow } from "./csv";

export interface StudyWorkspace {
  format: "styrkeanalyse-fdm-study";
  version: 1;
  id?: string;
  saved_at: string;
  analysis_time?: string;
  study_name: string;
  source_file_name: string;
  columns: string[];
  rows: CsvRow[];
  settings: Record<string, string | number>;
  result: unknown | null;
}

export function parseWorkspaceText(text: string): StudyWorkspace {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    throw new Error("This is not valid JSON.");
  }
  if (!value || typeof value !== "object") {
    throw new Error("This is not a supported StyrkeAnalyse study workspace.");
  }
  const workspace = value as Partial<StudyWorkspace>;
  if (
    workspace.format !== "styrkeanalyse-fdm-study" ||
    workspace.version !== 1 ||
    !Array.isArray(workspace.columns) ||
    !Array.isArray(workspace.rows) ||
    typeof workspace.study_name !== "string" ||
    typeof workspace.source_file_name !== "string"
  ) {
    throw new Error("This is not a supported StyrkeAnalyse study workspace.");
  }
  if (!workspace.rows.every((row) => row && typeof row === "object" && !Array.isArray(row))) {
    throw new Error("The workspace contains invalid measurement rows.");
  }
  return {
    format: "styrkeanalyse-fdm-study",
    version: 1,
    id: typeof workspace.id === "string" ? workspace.id : undefined,
    saved_at: typeof workspace.saved_at === "string" ? workspace.saved_at : "",
    analysis_time: typeof workspace.analysis_time === "string" ? workspace.analysis_time : "",
    study_name: workspace.study_name,
    source_file_name: workspace.source_file_name,
    columns: workspace.columns.filter((column): column is string => typeof column === "string"),
    rows: workspace.rows as CsvRow[],
    settings: workspace.settings && typeof workspace.settings === "object" ? workspace.settings : {},
    result: workspace.result ?? null,
  };
}
