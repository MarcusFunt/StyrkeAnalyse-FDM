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

  it("rejects a file without a usable header", () => {
    expect(() => parseCsvText("\n\n")).toThrow("header row");
  });
});
