import { describe, expect, it } from "vitest";
import { analysisInputFingerprint, guessColumn, isAnalysisInputValid, isAnalysisSnapshotCurrent } from "./analysisReadiness";

describe("analysis setup validation", () => {
  const columns = ["force_N", "displacement_mm", "temperature_C"];

  it("leaves unmatched columns unmapped", () => {
    expect(guessColumn(columns, /extension/i)).toBe("");
  });

  it("maps headers by name when a match exists", () => {
    expect(guessColumn(columns, /displacement|extension/i)).toBe("displacement_mm");
  });

  it("requires two existing, distinct measurement columns", () => {
    expect(isAnalysisInputValid(columns, "force_N", "displacement_mm", "10", "2", "50")).toBe(true);
    expect(isAnalysisInputValid(columns, "force_N", "force_N", "10", "2", "50")).toBe(false);
    expect(isAnalysisInputValid(columns, "force_N", "missing", "10", "2", "50")).toBe(false);
  });

  it.each(["", "0", "-1", "Infinity", "NaN"])("rejects invalid dimensions (%s)", (value) => {
    expect(isAnalysisInputValid(columns, "force_N", "displacement_mm", value, "2", "50")).toBe(false);
  });

  it("detects changes to data, settings, source bytes, or active specimen during analysis", () => {
    const submitted = analysisInputFingerprint({
      rows: [{ F: "10", D: "0" }],
      columns: ["F", "D"],
      settings: { widthMm: "10" },
      inputSha256: "a",
      specimenId: "S1",
    });
    const changed = analysisInputFingerprint({
      rows: [{ F: "10", D: "0" }],
      columns: ["F", "D"],
      settings: { widthMm: "11" },
      inputSha256: "a",
      specimenId: "S1",
    });

    expect(isAnalysisSnapshotCurrent(submitted, submitted)).toBe(true);
    expect(isAnalysisSnapshotCurrent(submitted, changed)).toBe(false);
  });
});
