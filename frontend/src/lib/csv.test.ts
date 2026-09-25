import { describe, expect, it } from "vitest";
import { parseCsvText } from "./csv";

describe("parseCsvText", () => {
  it("detects a semicolon CSV with decimal commas and keeps values as text", () => {
    const parsed = parseCsvText("Load;Travel\n0,20;0,5\n0,85;1,5");

    expect(parsed.columns).toEqual(["Load", "Travel"]);
    expect(parsed.rows).toEqual([
      { Load: "0,20", Travel: "0,5" },
      { Load: "0,85", Travel: "1,5" },
    ]);
    expect(parsed.warnings).toEqual([]);
  });

  it.each([
    ["tab", "force\tdisplacement\n1\t0.1", ["force", "displacement"]],
    ["pipe", "force|displacement\n1|0.1", ["force", "displacement"]],
    ["comma", "force,displacement\n1,0.1", ["force", "displacement"]],
  ])("uses the formal parser delimiter set for %s input", (_label, source, columns) => {
    expect(parseCsvText(source).columns).toEqual(columns);
  });

  it("rejects a file without a usable header", () => {
    expect(() => parseCsvText("\n\n")).toThrow("header row");
  });

  it("uses normalized headers as row keys", () => {
    const parsed = parseCsvText(" force_N , displacement_mm \n10, 0.2 \n20, 0.4");

    expect(parsed.columns).toEqual(["force_N", "displacement_mm"]);
    expect(parsed.rows).toEqual([
      { force_N: "10", displacement_mm: " 0.2 " },
      { force_N: "20", displacement_mm: " 0.4" },
    ]);
  });

  it("rejects headers that become duplicates after trimming", () => {
    expect(() => parseCsvText("force_N, force_N \n10,20")).toThrow(/duplicate.*force_N/i);
  });

  it("rejects empty header cells instead of silently shifting data", () => {
    expect(() => parseCsvText("force_N,,displacement_mm\n10,20,0.2")).toThrow(/empty header/i);
  });

  it("rejects data rows with extra cells instead of dropping values", () => {
    expect(() => parseCsvText("force_N,displacement_mm\n10,0.2,unexpected")).toThrow(/more values than the CSV header/i);
  });
});
