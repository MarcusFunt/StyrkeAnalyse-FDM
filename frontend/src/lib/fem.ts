export type FemJobStatus = "idle" | "preparing" | "queued" | "running" | "succeeded" | "failed";

export interface FemFormValues {
  specimenId: string;
  lengthMm: string;
  widthMm: string;
  thicknessMm: string;
  materialProfileId: string;
  youngsModulusMpa: string;
  poissonsRatio: string;
  forceN: string;
  maxCellSizeMm: string;
  elementOrder: 1 | 2;
  optimize: boolean;
}

export interface IsotropicTensileRequest {
  schema_version: 1;
  specimen: {
    specimen_id: string;
    length_mm: number;
    width_mm: number;
    thickness_mm: number;
  };
  material: {
    profile_id: string;
    youngs_modulus_mpa: number;
    poissons_ratio: number;
  };
  load: { force_n: number };
  boundary_conditions: {
    axial_axis: "x";
    fixed_axial_face: "x_min";
    prescribed_axial_face: "x_max";
    set_id: string;
    transverse_rigid_mode_control: "3d_minimal_rigid_mode_pins";
    unloaded_faces: "traction_free";
  };
  mesh: {
    max_cell_size_mm: number;
    element_order: 1 | 2;
    optimize: boolean;
  };
}

export interface RunSubmissionPayload {
  operation: "fdm-l2-isotropic";
  input_file: {
    filename: "request.json";
    media_type: "application/vnd.styrkeanalyse.fem-request+json";
    sha256: string;
    content_base64: string;
  };
  parameters: Record<string, never>;
  upstream_run_ids: [];
}

const SAFE_IDENTIFIER = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/;
const FLOAT_FIELDS = new Set([
  "force_n",
  "length_mm",
  "max_cell_size_mm",
  "poissons_ratio",
  "thickness_mm",
  "width_mm",
  "youngs_modulus_mpa",
]);

function parseFiniteNumber(value: string, label: string): number {
  if (!value.trim()) throw new Error(`${label} is required.`);
  const number = Number(value);
  if (!Number.isFinite(number)) throw new Error(`${label} must be finite.`);
  return number;
}

function positive(value: number, label: string, maximum: number): void {
  if (value <= 0 || value > maximum) {
    throw new Error(`${label} must be greater than zero and no more than ${maximum}.`);
  }
}

export function buildIsotropicTensileRequest(form: FemFormValues): IsotropicTensileRequest {
  const specimenId = form.specimenId.trim();
  if (!SAFE_IDENTIFIER.test(specimenId)) {
    throw new Error("Specimen ID must be a safe identifier (letters, numbers, dot, dash, colon, underscore).");
  }
  const profileId = form.materialProfileId.trim();
  if (!SAFE_IDENTIFIER.test(profileId)) throw new Error("Material profile ID must be a safe identifier.");

  const length = parseFiniteNumber(form.lengthMm, "Length");
  const width = parseFiniteNumber(form.widthMm, "Width");
  const thickness = parseFiniteNumber(form.thicknessMm, "Thickness");
  const modulus = parseFiniteNumber(form.youngsModulusMpa, "Young's modulus");
  const poissonsRatio = parseFiniteNumber(form.poissonsRatio, "Poisson's ratio");
  const force = parseFiniteNumber(form.forceN, "Axial force");
  const maxCellSize = parseFiniteNumber(form.maxCellSizeMm, "Maximum element size");

  positive(length, "Length", 1000);
  positive(width, "Width", 500);
  positive(thickness, "Thickness", 100);
  positive(modulus, "Young's modulus", 1_000_000);
  positive(force, "Axial force", 1_000_000_000);
  positive(maxCellSize, "Maximum element size", 100);
  if (length <= width) throw new Error("Length must exceed width for the rectangular tensile fixture.");
  if (width < thickness) throw new Error("Width must be at least thickness.");
  if (poissonsRatio <= -1 || poissonsRatio >= 0.5) {
    throw new Error("Poisson's ratio must be greater than -1 and less than 0.5.");
  }
  if (form.elementOrder !== 1 && form.elementOrder !== 2) {
    throw new Error("Element order must be P1 or P2.");
  }
  if (typeof form.optimize !== "boolean") throw new Error("Mesh optimization must be selected.");

  return {
    schema_version: 1,
    specimen: {
      specimen_id: specimenId,
      length_mm: length,
      width_mm: width,
      thickness_mm: thickness,
    },
    material: {
      profile_id: profileId,
      youngs_modulus_mpa: modulus,
      poissons_ratio: poissonsRatio,
    },
    load: { force_n: force },
    boundary_conditions: {
      axial_axis: "x",
      fixed_axial_face: "x_min",
      prescribed_axial_face: "x_max",
      set_id: "gui-tensile-axial-v1",
      transverse_rigid_mode_control: "3d_minimal_rigid_mode_pins",
      unloaded_faces: "traction_free",
    },
    mesh: { max_cell_size_mm: maxCellSize, element_order: form.elementOrder, optimize: form.optimize },
  };
}

function pythonFloatJson(value: number): string {
  if (Object.is(value, -0)) return "-0.0";
  const absolute = Math.abs(value);
  const text = value.toString().toLowerCase();
  if (absolute === 0) return "0.0";
  if (absolute >= 1e-4 && absolute < 1e16) {
    return text.includes(".") ? text : `${text}.0`;
  }

  let mantissa: string;
  let exponent: number;
  if (text.includes("e")) {
    const parts = text.split("e");
    mantissa = parts[0];
    exponent = Number(parts[1]);
  } else {
    const unsigned = text.startsWith("-") ? text.slice(1) : text;
    const decimalPosition = unsigned.indexOf(".") === -1 ? unsigned.length : unsigned.indexOf(".");
    const digits = unsigned.replace(".", "");
    const firstSignificantDigit = digits.search(/[1-9]/);
    exponent = decimalPosition - firstSignificantDigit - 1;
    const significantDigits = digits.slice(firstSignificantDigit).replace(/0+$/, "");
    mantissa = `${text.startsWith("-") ? "-" : ""}${significantDigits.length > 1
      ? `${significantDigits[0]}.${significantDigits.slice(1)}`
      : significantDigits}`;
  }
  const sign = exponent < 0 ? "-" : "+";
  return `${mantissa}e${sign}${Math.abs(exponent).toString().padStart(2, "0")}`;
}

function canonicalJson(value: unknown, key?: string): string {
  if (value === null || typeof value !== "object") {
    if (typeof value === "number") {
      if (!Number.isFinite(value)) throw new Error("FEM request numbers must be finite.");
      return key && FLOAT_FIELDS.has(key) ? pythonFloatJson(value) : String(value);
    }
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) return `[${value.map((item) => canonicalJson(item)).join(",")}]`;
  const entries = Object.entries(value as Record<string, unknown>).sort(([left], [right]) =>
    left < right ? -1 : left > right ? 1 : 0,
  );
  return `{${entries.map(([name, item]) => `${JSON.stringify(name)}:${canonicalJson(item, name)}`).join(",")}}`;
}

function base64(bytes: Uint8Array): string {
  let binary = "";
  const chunkSize = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
  }
  return btoa(binary);
}

export async function createFemSubmission(
  request: IsotropicTensileRequest,
): Promise<RunSubmissionPayload> {
  const canonicalBytes = new TextEncoder().encode(`${canonicalJson(request)}\n`);
  const digest = await crypto.subtle.digest("SHA-256", canonicalBytes);
  const sha256 = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
  return {
    operation: "fdm-l2-isotropic",
    input_file: {
      filename: "request.json",
      media_type: "application/vnd.styrkeanalyse.fem-request+json",
      sha256,
      content_base64: base64(canonicalBytes),
    },
    parameters: {},
    upstream_run_ids: [],
  };
}
