import { describe, expect, it } from "vitest";
import { buildIsotropicTensileRequest, createFemSubmission, type FemFormValues } from "./fem";

const validForm: FemFormValues = {
  specimenId: "SYN-T01",
  specimenShape: "rectangular",
  lengthMm: "50",
  widthMm: "10",
  thicknessMm: "2",
  materialProfileId: "PLA-isotropic-v1",
  youngsModulusMpa: "2000",
  poissonsRatio: "0.35",
  forceN: "100",
  maxCellSizeMm: "2.5",
  elementOrder: 2,
  optimize: true,
};

describe("isotropic tensile request", () => {
  it("test_build_isotropic_tensile_request_keeps_units_and_mesh_order_explicit", () => {
    expect(buildIsotropicTensileRequest(validForm)).toEqual({
      schema_version: 1,
      specimen: {
        specimen_id: "SYN-T01",
        length_mm: 50,
        width_mm: 10,
        thickness_mm: 2,
      },
      material: {
        profile_id: "PLA-isotropic-v1",
        youngs_modulus_mpa: 2000,
        poissons_ratio: 0.35,
      },
      load: { force_n: 100 },
      boundary_conditions: {
        axial_axis: "x",
        fixed_axial_face: "x_min",
        prescribed_axial_face: "x_max",
        set_id: "gui-tensile-axial-v1",
        transverse_rigid_mode_control: "3d_minimal_rigid_mode_pins",
        unloaded_faces: "traction_free",
      },
      mesh: { max_cell_size_mm: 2.5, element_order: 2, optimize: true },
    });
  });

  it("test_create_fem_submission_hashes_exact_canonical_bytes", async () => {
    const request = buildIsotropicTensileRequest(validForm);
    const submission = await createFemSubmission(request);
    const canonical = [
      '{"boundary_conditions":{"axial_axis":"x","fixed_axial_face":"x_min","prescribed_axial_face":"x_max","set_id":"gui-tensile-axial-v1","transverse_rigid_mode_control":"3d_minimal_rigid_mode_pins","unloaded_faces":"traction_free"},',
      '"load":{"force_n":100.0},',
      '"material":{"poissons_ratio":0.35,"profile_id":"PLA-isotropic-v1","youngs_modulus_mpa":2000.0},',
      '"mesh":{"element_order":2,"max_cell_size_mm":2.5,"optimize":true},',
      '"schema_version":1,',
      '"specimen":{"length_mm":50.0,"specimen_id":"SYN-T01","thickness_mm":2.0,"width_mm":10.0}}',
      "\n",
    ].join("");
    const bytes = new TextEncoder().encode(canonical);
    const content = atob(submission.input_file.content_base64);
    const digest = await crypto.subtle.digest("SHA-256", bytes);
    const expectedSha256 = Array.from(new Uint8Array(digest), (value) =>
      value.toString(16).padStart(2, "0"),
    ).join("");

    expect(submission).toMatchObject({
      operation: "fdm-l2-isotropic",
      input_file: {
        filename: "request.json",
        media_type: "application/vnd.styrkeanalyse.fem-request+json",
        sha256: expectedSha256,
      },
      parameters: {},
      upstream_run_ids: [],
    });
    expect(content).toBe(canonical);
    expect("image_reference" in submission).toBe(false);
    expect("command" in submission).toBe(false);
  });

  it("test_build_isotropic_tensile_request_rejects_invalid_dimensions_and_material", () => {
    expect(() => buildIsotropicTensileRequest({ ...validForm, lengthMm: "10" })).toThrow(
      /length must exceed width/i,
    );
    expect(() => buildIsotropicTensileRequest({ ...validForm, thicknessMm: "12" })).toThrow(
      /width must be at least thickness/i,
    );
    expect(() => buildIsotropicTensileRequest({ ...validForm, poissonsRatio: "0.5" })).toThrow(
      /poisson/i,
    );
    expect(() => buildIsotropicTensileRequest({ ...validForm, youngsModulusMpa: "0" })).toThrow(
      /modulus/i,
    );
    expect(() => buildIsotropicTensileRequest({ ...validForm, specimenId: "unsafe id" })).toThrow(
      /specimen ID/i,
    );
  });
  it("builds a versioned full ASTM D638 request without pretending it is rectangular", () => {
    const request = buildIsotropicTensileRequest({
      ...validForm,
      specimenShape: "IV",
      specimenId: "ASTM-IV-01",
      thicknessMm: "3.2",
    });

    expect(request).toEqual({
      schema_version: 2,
      specimen: {
        specimen_id: "ASTM-IV-01",
        standard_revision: "ASTM D638-22",
        specimen_type: "IV",
        thickness_mm: 3.2,
      },
      material: {
        profile_id: "PLA-isotropic-v1",
        youngs_modulus_mpa: 2000,
        poissons_ratio: 0.35,
      },
      load: { force_n: 100 },
      boundary_conditions: {
        axial_axis: "x",
        fixed_axial_face: "x_min",
        loaded_face: "x_max",
        load_control: "uniform_end_traction",
        set_id: "astm-d638-end-traction-v1",
        transverse_rigid_mode_control: "3d_minimal_rigid_mode_pins",
        unloaded_faces: "traction_free",
      },
      mesh: { max_cell_size_mm: 2.5, element_order: 2, optimize: true },
    });
  });

});
