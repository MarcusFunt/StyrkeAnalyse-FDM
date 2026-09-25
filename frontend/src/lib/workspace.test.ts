import { describe, expect, it } from "vitest";
import { parseWorkspaceText } from "./workspace";

const validV1 = {
  format: "styrkeanalyse-fdm-study",
  version: 1,
  study_name: "PLA tensile study",
  source_file_name: "test.csv",
  columns: ["force_N", "displacement_mm"],
  rows: [{ force_N: "10", displacement_mm: "0.1" }],
  settings: { widthMm: "10", thicknessMm: "2", gaugeLengthMm: "50" },
  result: null,
};

function validV2(): any {
  return {
    format: "styrkeanalyse-fdm-study",
    version: 2,
    study_name: "PLA campaign",
    campaign: {
      id: "campaign-1",
      name: "PLA campaign",
      configurations: [{ id: "cfg-1", label: "0/90" }],
    },
    specimens: [
      {
        id: "S01",
        label: "S01",
        configuration_id: "cfg-1",
        geometry: { width_mm: 10, thickness_mm: 2, gauge_length_mm: 50 },
        print_metadata: { material: "PLA", manufacturer: "Example Polymers" },
        test_runs: [
          {
            id: "run-1",
            sensor_source: "extensometer",
            compliance_correction: { method: "not_required" },
            input_file: {
              filename: "coupon.csv",
              media_type: "text/csv",
              size_bytes: 128,
              sha256: "a".repeat(64),
              imported_at: "2026-09-24T10:00:00Z",
              status: "verified",
            },
            columns: ["F", "D"],
            rows: [{ F: "10", D: "0" }],
            settings: {},
            result: null,
          },
        ],
      },
    ],
  };
}

describe("parseWorkspaceText", () => {
  it("migrates a v1 workspace without inventing unavailable metadata", () => {
    const workspace = parseWorkspaceText(JSON.stringify(validV1));
    const specimen = workspace.specimens[0];
    const testRun = specimen.test_runs[0];

    expect(workspace.version).toBe(3);
    expect(workspace.campaign.name).toBe("PLA tensile study");
    expect(workspace.campaign.reduction_run_id).toBeNull();
    expect(specimen.geometry.width_mm).toBe(10);
    expect(specimen.print_metadata.material).toBeNull();
    expect(testRun.sensor_source).toBe("unknown");
    expect(testRun.input_file.status).toBe("unavailable_legacy");
    expect(testRun.input_file.sha256).toBeNull();
    expect(testRun.rows).toEqual(validV1.rows);
  });

  it("preserves a host study ID while migrating a legacy workspace", () => {
    const workspace = parseWorkspaceText(JSON.stringify({
      ...validV1,
      id: "4b1341bd-3336-4080-aac7-8f9f1c276de0",
    }));
    expect(workspace.id).toBe("4b1341bd-3336-4080-aac7-8f9f1c276de0");
  });

  it("validates v2 specimen, sensor, and verified input-file provenance", () => {
    const workspace = parseWorkspaceText(JSON.stringify(validV2()));
    expect(workspace.specimens[0].test_runs[0].sensor_source).toBe("extensometer");
    expect(workspace.specimens[0].test_runs[0].input_file.sha256).toBe("a".repeat(64));
  });

  it("preserves an immutable Run link on its specimen test run", () => {
    const payload = validV2();
    payload.specimens[0].test_runs[0].run_id = "8e02d8f8-b1ab-4abc-9fe5-2f65173b6704";

    expect(parseWorkspaceText(JSON.stringify(payload)).specimens[0].test_runs[0].run_id)
      .toBe(payload.specimens[0].test_runs[0].run_id);
    payload.specimens[0].test_runs[0].run_id = "bad-id";
    expect(() => parseWorkspaceText(JSON.stringify(payload))).toThrow(/test-run metadata/i);
  });

  it("migrates v2 controlled print metadata into Configuration without inventing unknowns", () => {
    const workspace = parseWorkspaceText(JSON.stringify(validV2()));
    expect(workspace.version).toBe(3);
    expect(workspace.campaign.configurations[0].material).toBe("PLA");
    expect(workspace.campaign.configurations[0].manufacturer).toBe("Example Polymers");
    expect(workspace.campaign.configurations[0].printer).toBeNull();
    expect(workspace.specimens[0].print_metadata.material).toBeNull();
    expect(workspace.specimens[0].print_metadata.manufacturer).toBeNull();
  });

  it("rejects v2 specimens with incompatible controlled conditions in one configuration", () => {
    const payload = validV2();
    payload.specimens.push({
      ...structuredClone(payload.specimens[0]),
      id: "S02",
      label: "S02",
      print_metadata: { ...payload.specimens[0].print_metadata, material: "ABS" },
      test_runs: [{ ...payload.specimens[0].test_runs[0], id: "run-2" }],
    });
    expect(() => parseWorkspaceText(JSON.stringify(payload))).toThrow(/configuration/i);
  });

  it("rejects invalid JSON and unsupported versions", () => {
    expect(() => parseWorkspaceText("not JSON")).toThrow("valid JSON");
    expect(() => parseWorkspaceText('{"format":"other","version":9}')).toThrow(
      "not a supported StyrkeAnalyse study workspace",
    );
  });

  it.each([
    ["unparseable analysis timestamp", { analysis_time: "yesterday-ish" }],
    ["unknown legacy field", { hidden_result: 42 }],
    ["non-numeric dimension", { settings: { ...validV1.settings, widthMm: "NaN" } }],
  ])("rejects a malformed v1 workspace with %s", (_label, patch) => {
    expect(() => parseWorkspaceText(JSON.stringify({ ...validV1, ...patch }))).toThrow();
  });

  it.each([
    ["non-string legacy column", { columns: ["force_N", 7] }],
    ["duplicate legacy columns", { columns: ["force_N", "force_N"] }],
    ["nested legacy measurement value", { rows: [{ force_N: { value: "10" } }] }],
    ["non-object legacy settings", { settings: [] }],
    ["non-object legacy result", { result: [] }],
    ["malformed legacy result summary", { result: { summary: {}, points: [] } }],
    ["malformed legacy result point", { result: { summary: validSummary(), points: [{}] } }],
  ])("rejects a v1 workspace with a %s", (_label, override) => {
    expect(() => parseWorkspaceText(JSON.stringify({ ...validV1, ...override }))).toThrow();
  });

  it.each([
    ["invalid sensor", (workspace: ReturnType<typeof validV2>) => { workspace.specimens[0].test_runs[0].sensor_source = "laser"; }],
    ["invalid digest", (workspace: ReturnType<typeof validV2>) => { workspace.specimens[0].test_runs[0].input_file.sha256 = "bad"; }],
    ["missing configuration", (workspace: ReturnType<typeof validV2>) => { workspace.specimens[0].configuration_id = "missing"; }],
    ["nested row", (workspace: ReturnType<typeof validV2>) => { workspace.specimens[0].test_runs[0].rows[0].F = { value: "10" }; }],
    ["invalid print date", (workspace: ReturnType<typeof validV2>) => { workspace.specimens[0].print_metadata.print_date = "2026-02-31"; }],
    ["multiple primary test runs", (workspace: ReturnType<typeof validV2>) => {
      workspace.specimens[0].test_runs.push({ ...workspace.specimens[0].test_runs[0], id: "run-2" });
    }],
    ["mismatched row columns", (workspace: ReturnType<typeof validV2>) => { workspace.specimens[0].test_runs[0].rows[0].extra = "value"; }],
    ["out-of-range dimensions", (workspace: ReturnType<typeof validV2>) => { workspace.specimens[0].geometry.width_mm = -1; }],
  ])("rejects a v2 workspace with %s", (_label, mutate) => {
    const workspace = validV2();
    mutate(workspace);
    expect(() => parseWorkspaceText(JSON.stringify(workspace))).toThrow();
  });

  it("rejects results detached from raw row count or specimen dimensions", () => {
    const workspace = validV2();
    const run = workspace.specimens[0].test_runs[0];
    run.result = {
      summary: validSummary(),
      points: [{
        row_number: 1,
        force_n: 10,
        displacement_mm: 0,
        extension_mm: 0,
        strain: 0,
        stress_mpa: 0.5,
      }],
    };
    run.rows.push({ F: "20", D: "0.1" });
    expect(() => parseWorkspaceText(JSON.stringify(workspace))).toThrow(/sample count/i);

    run.rows.pop();
    workspace.specimens[0].geometry.width_mm = 11;
    expect(() => parseWorkspaceText(JSON.stringify(workspace))).toThrow(/area/i);
  });
});

function validSummary() {
  return {
    sample_count: 1,
    cross_section_area_mm2: 20,
    gauge_length_mm: 50,
    peak_force_n: 10,
    peak_force_row: 1,
    peak_stress_mpa: 0.5,
    peak_stress_row: 1,
  };
}
