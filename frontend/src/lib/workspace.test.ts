import { describe, expect, it } from "vitest";
import { parseWorkspaceText } from "./workspace";

describe("parseWorkspaceText", () => {
  it("accepts a versioned local study workspace", () => {
    const workspace = {
      format: "styrkeanalyse-fdm-study",
      version: 1,
      study_name: "PLA tensile study",
      source_file_name: "test.csv",
      columns: ["force_N", "displacement_mm"],
      rows: [{ force_N: "10", displacement_mm: "0.1" }],
    };

    expect(parseWorkspaceText(JSON.stringify(workspace)).study_name).toBe("PLA tensile study");
  });

  it("preserves a host study ID when opening a saved workspace", () => {
    const workspace = parseWorkspaceText(JSON.stringify({
      format: "styrkeanalyse-fdm-study",
      version: 1,
      id: "4b1341bd-3336-4080-aac7-8f9f1c276de0",
      study_name: "Desktop study",
      source_file_name: "test.csv",
      columns: [],
      rows: [],
    }));

    expect(workspace.id).toBe("4b1341bd-3336-4080-aac7-8f9f1c276de0");
  });

  it("rejects unsupported workspace formats and versions", () => {
    expect(() => parseWorkspaceText('{"format":"other","version":1}')).toThrow(
      "not a supported StyrkeAnalyse study workspace",
    );
  });
});
