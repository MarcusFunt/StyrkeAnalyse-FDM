import type { CsvRow } from "./csv";

export interface AnalysisPoint {
  row_number: number;
  force_n: number;
  displacement_mm: number;
  extension_mm: number;
  strain: number;
  stress_mpa: number;
}

export interface AnalysisResponse {
  summary: {
    sample_count: number;
    cross_section_area_mm2: number;
    gauge_length_mm: number;
    peak_force_n: number;
    peak_force_row: number;
    peak_stress_mpa: number;
    peak_stress_row: number;
  };
  points: AnalysisPoint[];
}

export type WorkspaceSetting = string | number | boolean | null;
export type SensorSource = "unknown" | "extensometer" | "crosshead" | "clip_gauge" | "dic" | "other";
export type ComplianceMethod = "unknown" | "not_required" | "machine_compliance" | "other";

export interface InputFileProvenance {
  filename: string;
  media_type: string | null;
  size_bytes: number | null;
  sha256: string | null;
  imported_at: string | null;
  status: "verified" | "unavailable_legacy";
}

export interface PrintMetadata {
  material: string | null;
  manufacturer: string | null;
  material_lot: string | null;
  printer: string | null;
  nozzle: string | null;
  nozzle_diameter_mm: number | null;
  layer_height_mm: number | null;
  raster_orientation: string | null;
  infill_percent: number | null;
  nozzle_temperature_c: number | null;
  bed_temperature_c: number | null;
  print_date: string | null;
  gcode_sha256: string | null;
}

export interface Geometry {
  width_mm: number | null;
  thickness_mm: number | null;
  gauge_length_mm: number | null;
}

export interface StudyTestRun {
  id: string;
  run_id: string | null;
  primary_for_reduction: boolean;
  analysis_time: string | null;
  test_date: string | null;
  test_type: string | null;
  test_standard: string | null;
  operator: string | null;
  machine: string | null;
  load_cell: string | null;
  sensor_source: SensorSource;
  sensor_source_description: string | null;
  compliance_correction: {
    method: ComplianceMethod;
    compliance_mm_per_n: number | null;
    calibration_source: string | null;
    notes: string | null;
  };
  input_file: InputFileProvenance;
  columns: string[];
  rows: CsvRow[];
  settings: Record<string, WorkspaceSetting>;
  result: AnalysisResponse | null;
}

export interface StudyConfiguration {
  id: string;
  label: string;
  material: string | null;
  manufacturer: string | null;
  material_lot: string | null;
  printer: string | null;
  print_profile: string | null;
  nozzle: string | null;
  nozzle_diameter_mm: number | null;
  layer_height_mm: number | null;
  orientation: string | null;
  build_orientation: string | null;
  raster_strategy: string | null;
  infill_percent: number | null;
  nozzle_temperature_c: number | null;
  bed_temperature_c: number | null;
  nominal_geometry: Geometry | null;
  test_type: string | null;
  test_standard_revision: string | null;
}

export interface StudyWorkspace {
  format: "styrkeanalyse-fdm-study";
  version: 3;
  id?: string;
  revision?: number;
  saved_at?: string;
  study_name: string;
  campaign: {
    id: string;
    name: string;
    reduction_run_id: string | null;
    notes: string | null;
    created_at: string | null;
    configurations: StudyConfiguration[];
  };
  specimens: Array<{
    id: string;
    label: string;
    configuration_id: string;
    geometry: Geometry;
    print_metadata: PrintMetadata;
    test_runs: StudyTestRun[];
  }>;
}

const sensorSources: SensorSource[] = ["unknown", "extensometer", "crosshead", "clip_gauge", "dic", "other"];
const complianceMethods: ComplianceMethod[] = ["unknown", "not_required", "machine_compliance", "other"];
const topLevelKeys = ["format", "version", "id", "revision", "saved_at", "study_name", "campaign", "specimens"];
const legacyTopLevelKeys = ["format", "version", "id", "revision", "saved_at", "analysis_time", "study_name", "source_file_name", "columns", "rows", "settings", "result"];
const campaignKeys = ["id", "name", "reduction_run_id", "notes", "created_at", "configurations"];
const configurationKeys = [
  "id", "label", "material", "manufacturer", "material_lot", "printer", "print_profile", "nozzle",
  "nozzle_diameter_mm", "layer_height_mm", "orientation", "build_orientation", "raster_strategy",
  "infill_percent", "nozzle_temperature_c", "bed_temperature_c", "nominal_geometry", "test_type",
  "test_standard_revision",
];
const specimenKeys = ["id", "label", "configuration_id", "geometry", "print_metadata", "test_runs"];
const geometryKeys = ["width_mm", "thickness_mm", "gauge_length_mm"];
const testRunKeys = [
  "id", "run_id", "primary_for_reduction", "analysis_time", "test_date", "test_type", "test_standard", "operator",
  "machine", "load_cell", "sensor_source", "sensor_source_description", "compliance_correction",
  "input_file", "columns", "rows", "settings", "result",
];
const complianceKeys = ["method", "compliance_mm_per_n", "calibration_source", "notes"];
const inputFileKeys = ["filename", "media_type", "size_bytes", "sha256", "imported_at", "status"];
const resultSummaryKeys = [
  "sample_count", "cross_section_area_mm2", "gauge_length_mm", "peak_force_n", "peak_force_row",
  "peak_stress_mpa", "peak_stress_row",
];
const resultPointKeys = ["row_number", "force_n", "displacement_mm", "extension_mm", "strain", "stress_mpa"];
const printMetadataKeys = [
  "material", "manufacturer", "material_lot", "printer", "nozzle", "nozzle_diameter_mm",
  "layer_height_mm", "raster_orientation", "infill_percent", "nozzle_temperature_c",
  "bed_temperature_c", "print_date", "gcode_sha256",
];

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function onlyKeys(value: Record<string, unknown>, allowed: string[], label: string): void {
  const extra = Object.keys(value).find((key) => !allowed.includes(key));
  if (extra) throw new Error(`The workspace contains an unknown ${label} field: ${extra}.`);
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isIsoTimestamp(value: unknown): value is string {
  return typeof value === "string" &&
    /(?:Z|[+-]\d{2}:\d{2})$/i.test(value) &&
    Number.isFinite(Date.parse(value));
}

function isDateOnly(value: unknown): value is string {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().startsWith(value);
}

function parseScalarRecord(value: unknown, label: string): Record<string, WorkspaceSetting> {
  if (!isRecord(value)) throw new Error(`The workspace contains invalid ${label}.`);
  if (Object.values(value).some((item) =>
    item !== null && typeof item !== "string" && typeof item !== "boolean" && !isFiniteNumber(item),
  )) {
    throw new Error(`The workspace contains invalid ${label}.`);
  }
  return value as Record<string, WorkspaceSetting>;
}

function parseRows(value: unknown, label: string): CsvRow[] {
  if (!Array.isArray(value) || !value.every((row) =>
    isRecord(row) && Object.entries(row).every(([key, cell]) => Boolean(key) && typeof cell === "string"),
  )) {
    throw new Error(`The workspace contains invalid ${label}.`);
  }
  return value as CsvRow[];
}

function parseColumns(value: unknown, label: string): string[] {
  if (
    !Array.isArray(value) ||
    value.some((column) => typeof column !== "string" || !column || column !== column.trim()) ||
    new Set(value).size !== value.length
  ) {
    throw new Error(`The workspace contains invalid or duplicate ${label}.`);
  }
  return value as string[];
}

function parseAnalysisResult(value: unknown): AnalysisResponse | null {
  if (value === null || value === undefined) return null;
  if (!isRecord(value) || !isRecord(value.summary) || !Array.isArray(value.points)) {
    throw new Error("The workspace contains an invalid analysis result.");
  }
  onlyKeys(value, ["summary", "points"], "analysis result");
  const summary = value.summary;
  onlyKeys(summary, resultSummaryKeys, "analysis summary");
  const numericFields = [
    "cross_section_area_mm2", "gauge_length_mm", "peak_force_n", "peak_stress_mpa",
  ];
  if (
    !Number.isSafeInteger(summary.sample_count) ||
    Number(summary.sample_count) < 1 ||
    numericFields.some((field) => !isFiniteNumber(summary[field])) ||
    !Number.isSafeInteger(summary.peak_force_row) ||
    !Number.isSafeInteger(summary.peak_stress_row) ||
    Number(summary.cross_section_area_mm2) <= 0 || Number(summary.gauge_length_mm) <= 0 ||
    Number(summary.peak_force_n) < 0 || Number(summary.peak_stress_mpa) < 0 ||
    Number(summary.peak_force_row) < 1 || Number(summary.peak_stress_row) < 1 ||
    value.points.length !== summary.sample_count
  ) {
    throw new Error("The workspace contains an invalid analysis summary.");
  }
  const pointFields = ["force_n", "displacement_mm", "extension_mm", "strain", "stress_mpa"];
  const points = value.points.map((point, index) => {
    if (isRecord(point)) onlyKeys(point, resultPointKeys, "analysis point");
    if (
      !isRecord(point) || point.row_number !== index + 1 ||
      !pointFields.every((field) => isFiniteNumber(point[field]))
    ) {
      throw new Error(`The workspace contains an invalid analysis point at row ${index + 1}.`);
    }
    return point as unknown as AnalysisPoint;
  });
  if (
    Number(summary.peak_force_row) < 1 || Number(summary.peak_force_row) > points.length ||
    Number(summary.peak_stress_row) < 1 || Number(summary.peak_stress_row) > points.length
  ) {
    throw new Error("The workspace contains an invalid analysis summary row number.");
  }
  return value as unknown as AnalysisResponse;
}

function parsePrintMetadata(value: unknown): PrintMetadata {
  if (!isRecord(value)) throw new Error("The workspace contains invalid print metadata.");
  onlyKeys(value, printMetadataKeys, "print metadata");
  const normalized = Object.fromEntries(printMetadataKeys.map((key) => [key, value[key] ?? null]));
  const stringFields = ["material", "manufacturer", "material_lot", "printer", "nozzle", "raster_orientation", "print_date", "gcode_sha256"];
  if (stringFields.some((key) => normalized[key] !== null && typeof normalized[key] !== "string")) {
    throw new Error("The workspace contains invalid print metadata text.");
  }
  const numericFields = ["nozzle_diameter_mm", "layer_height_mm", "infill_percent", "nozzle_temperature_c", "bed_temperature_c"];
  if (numericFields.some((key) => normalized[key] !== null && !isFiniteNumber(normalized[key]))) {
    throw new Error("The workspace contains invalid print metadata numbers.");
  }
  if (
    normalized.gcode_sha256 !== null && !/^[0-9a-f]{64}$/.test(String(normalized.gcode_sha256)) ||
    normalized.infill_percent !== null && (Number(normalized.infill_percent) < 0 || Number(normalized.infill_percent) > 100) ||
    normalized.print_date !== null && !isDateOnly(normalized.print_date)
  ) {
    throw new Error("The workspace contains invalid print metadata values.");
  }
  return normalized as unknown as PrintMetadata;
}

function parseGeometry(value: unknown): Geometry {
  if (!isRecord(value)) throw new Error("The workspace contains invalid specimen geometry.");
  onlyKeys(value, geometryKeys, "specimen geometry");
  const parseDimension = (dimension: unknown): number | null => {
    if (dimension === null || dimension === undefined) return null;
    if (!isFiniteNumber(dimension) || dimension <= 0) {
      throw new Error("Specimen dimensions must be finite positive numbers or unknown.");
    }
    return dimension;
  };
  return {
    width_mm: parseDimension(value.width_mm),
    thickness_mm: parseDimension(value.thickness_mm),
    gauge_length_mm: parseDimension(value.gauge_length_mm),
  };
}

function parseInputFile(value: unknown): InputFileProvenance {
  if (!isRecord(value)) throw new Error("The workspace contains invalid input-file provenance.");
  onlyKeys(value, inputFileKeys, "input-file provenance");
  const { filename, media_type, size_bytes, sha256, imported_at, status } = value;
  if (
    typeof filename !== "string" || !filename.trim() || filename.length > 255 ||
    media_type !== null && media_type !== undefined && typeof media_type !== "string" ||
    status !== "verified" && status !== "unavailable_legacy"
  ) {
    throw new Error("The workspace contains invalid input-file provenance.");
  }
  if (status === "verified") {
    if (
      !Number.isSafeInteger(size_bytes) || Number(size_bytes) < 0 ||
      typeof sha256 !== "string" || !/^[0-9a-f]{64}$/.test(sha256) ||
      !isIsoTimestamp(imported_at)
    ) {
      throw new Error("Verified input-file provenance requires a byte count, SHA-256, and import time.");
    }
  } else if (size_bytes != null || sha256 != null || imported_at != null) {
    throw new Error("Legacy input-file provenance cannot claim an unverified hash or size.");
  }
  return {
    filename,
    media_type: (media_type as string | null | undefined) ?? null,
    size_bytes: (size_bytes as number | null | undefined) ?? null,
    sha256: (sha256 as string | null | undefined) ?? null,
    imported_at: (imported_at as string | null | undefined) ?? null,
    status,
  };
}

function parseV2(value: Record<string, unknown>): StudyWorkspace {
  onlyKeys(value, topLevelKeys, "workspace");
  if (
    value.format !== "styrkeanalyse-fdm-study" || value.version !== 2 && value.version !== 3 ||
    typeof value.study_name !== "string" || !value.study_name.trim() || !isRecord(value.campaign) ||
    !Array.isArray(value.specimens) || value.specimens.length === 0
  ) {
    throw new Error("This is not a supported StyrkeAnalyse study workspace.");
  }
  const campaign = value.campaign;
  onlyKeys(campaign, campaignKeys, "campaign");
  if (
    typeof campaign.id !== "string" || !campaign.id || typeof campaign.name !== "string" ||
    !campaign.name.trim() || !Array.isArray(campaign.configurations) || campaign.configurations.length === 0 ||
    campaign.reduction_run_id != null && (typeof campaign.reduction_run_id !== "string" ||
      !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(campaign.reduction_run_id))
  ) {
    throw new Error("The workspace contains invalid campaign metadata.");
  }
  const configurations = campaign.configurations.map((configuration) => {
    if (isRecord(configuration)) onlyKeys(configuration, configurationKeys, "campaign configuration");
    if (!isRecord(configuration) || typeof configuration.id !== "string" || !configuration.id ||
      typeof configuration.label !== "string" || !configuration.label.trim()) {
      throw new Error("The workspace contains an invalid campaign configuration.");
    }
    const optionalText = [
      configuration.material, configuration.manufacturer, configuration.material_lot, configuration.printer,
      configuration.print_profile, configuration.nozzle, configuration.orientation,
      configuration.build_orientation, configuration.raster_strategy, configuration.test_type,
      configuration.test_standard_revision,
    ];
    if (optionalText.some((item) => item !== null && item !== undefined && typeof item !== "string")) {
      throw new Error("The workspace contains invalid optional configuration text.");
    }
    const optionalNumber = (key: string): number | null => {
      const raw = configuration[key];
      if (raw === null || raw === undefined) return null;
      if (!isFiniteNumber(raw)) throw new Error(`The workspace contains an invalid configuration value: ${key}.`);
      return raw;
    };
    const nozzleDiameter = optionalNumber("nozzle_diameter_mm");
    const layerHeight = optionalNumber("layer_height_mm");
    const infill = optionalNumber("infill_percent");
    const nozzleTemperature = optionalNumber("nozzle_temperature_c");
    const bedTemperature = optionalNumber("bed_temperature_c");
    if (
      nozzleDiameter !== null && nozzleDiameter <= 0 || layerHeight !== null && layerHeight <= 0 ||
      infill !== null && (infill < 0 || infill > 100)
    ) {
      throw new Error("The workspace contains an out-of-range configuration process value.");
    }
    return {
      id: configuration.id,
      label: configuration.label,
      material: typeof configuration.material === "string" ? configuration.material : null,
      manufacturer: typeof configuration.manufacturer === "string" ? configuration.manufacturer : null,
      material_lot: typeof configuration.material_lot === "string" ? configuration.material_lot : null,
      printer: typeof configuration.printer === "string" ? configuration.printer : null,
      print_profile: typeof configuration.print_profile === "string" ? configuration.print_profile : null,
      nozzle: typeof configuration.nozzle === "string" ? configuration.nozzle : null,
      nozzle_diameter_mm: nozzleDiameter,
      layer_height_mm: layerHeight,
      orientation: typeof configuration.orientation === "string" ? configuration.orientation : null,
      build_orientation: typeof configuration.build_orientation === "string" ? configuration.build_orientation : null,
      raster_strategy: typeof configuration.raster_strategy === "string" ? configuration.raster_strategy : null,
      infill_percent: infill,
      nozzle_temperature_c: nozzleTemperature,
      bed_temperature_c: bedTemperature,
      nominal_geometry: configuration.nominal_geometry == null ? null : parseGeometry(configuration.nominal_geometry),
      test_type: typeof configuration.test_type === "string" ? configuration.test_type : null,
      test_standard_revision: typeof configuration.test_standard_revision === "string"
        ? configuration.test_standard_revision
        : null,
    };
  });
  const configurationIds = configurations.map(({ id }) => id);
  if (new Set(configurationIds).size !== configurationIds.length) {
    throw new Error("Campaign configuration IDs must be unique.");
  }
  const seenSpecimens = new Set<string>();
  const seenRuns = new Set<string>();
  const specimens = value.specimens.map((specimenValue) => {
    if (isRecord(specimenValue)) onlyKeys(specimenValue, specimenKeys, "specimen");
    if (!isRecord(specimenValue) || typeof specimenValue.id !== "string" || !specimenValue.id ||
      typeof specimenValue.label !== "string" || !specimenValue.label.trim() ||
      typeof specimenValue.configuration_id !== "string" || !configurationIds.includes(specimenValue.configuration_id) ||
      !Array.isArray(specimenValue.test_runs)) {
      throw new Error("The workspace contains invalid specimen metadata or configuration references.");
    }
    if (seenSpecimens.has(specimenValue.id)) throw new Error("Campaign specimen IDs must be unique.");
    seenSpecimens.add(specimenValue.id);
    if (!isRecord(specimenValue.print_metadata)) throw new Error("The workspace contains invalid print metadata.");
    const geometry = parseGeometry(specimenValue.geometry);
    const testRuns = specimenValue.test_runs.map((runValue) => {
      if (isRecord(runValue)) onlyKeys(runValue, testRunKeys, "test run");
      if (!isRecord(runValue) || typeof runValue.id !== "string" || !runValue.id ||
        runValue.run_id != null && (typeof runValue.run_id !== "string" || !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(runValue.run_id)) ||
        !sensorSources.includes(runValue.sensor_source as SensorSource) ||
        !isRecord(runValue.compliance_correction) || !Array.isArray(runValue.columns)) {
        throw new Error("The workspace contains invalid test-run metadata.");
      }
      if (seenRuns.has(runValue.id)) throw new Error("Test-run IDs must be unique within a campaign.");
      seenRuns.add(runValue.id);
      const correction = runValue.compliance_correction;
      onlyKeys(correction, complianceKeys, "compliance correction");
      if (!complianceMethods.includes(correction.method as ComplianceMethod) ||
        correction.method === "machine_compliance" &&
          (!isFiniteNumber(correction.compliance_mm_per_n) || correction.compliance_mm_per_n <= 0 ||
            typeof correction.calibration_source !== "string" || !correction.calibration_source.trim()) ||
        correction.method !== "machine_compliance" && correction.compliance_mm_per_n != null ||
        correction.calibration_source != null && typeof correction.calibration_source !== "string" ||
        correction.notes != null && typeof correction.notes !== "string") {
        throw new Error("The workspace contains invalid compliance-correction metadata.");
      }
      if (runValue.sensor_source === "other" &&
        (typeof runValue.sensor_source_description !== "string" || !runValue.sensor_source_description.trim())) {
        throw new Error("Other sensor sources require a description.");
      }
      const columns = parseColumns(runValue.columns, "test columns");
      const inputFile = parseInputFile(runValue.input_file);
      if (runValue.primary_for_reduction !== undefined && typeof runValue.primary_for_reduction !== "boolean") {
        throw new Error("The workspace contains invalid test-run reduction selection.");
      }
      const rows = parseRows(runValue.rows, "test rows");
      const columnSet = new Set(columns);
      if (rows.some((row) => Object.keys(row).length !== columns.length || Object.keys(row).some((key) => !columnSet.has(key)))) {
        throw new Error("Each test row must contain exactly the named test columns.");
      }
      if (
        runValue.test_date != null && !isDateOnly(runValue.test_date) ||
        runValue.analysis_time != null && !isIsoTimestamp(runValue.analysis_time) ||
        [runValue.test_type, runValue.test_standard, runValue.operator, runValue.machine, runValue.load_cell, runValue.sensor_source_description]
          .some((item) => item != null && typeof item !== "string")
      ) {
        throw new Error("The workspace contains invalid test date or descriptive metadata.");
      }
      const result = parseAnalysisResult(runValue.result);
      if (result && result.summary.sample_count !== rows.length) {
        throw new Error("The analysis result sample count must match the imported test rows.");
      }
      if (result && geometry.width_mm !== null && geometry.thickness_mm !== null &&
          !closeEnough(result.summary.cross_section_area_mm2, geometry.width_mm * geometry.thickness_mm)) {
        throw new Error("The analysis result area does not match the specimen geometry.");
      }
      if (result && geometry.gauge_length_mm !== null &&
          !closeEnough(result.summary.gauge_length_mm, geometry.gauge_length_mm)) {
        throw new Error("The analysis result gauge length does not match the specimen geometry.");
      }
      return {
        id: runValue.id,
        run_id: typeof runValue.run_id === "string" ? runValue.run_id : null,
        primary_for_reduction: runValue.primary_for_reduction !== false,
        analysis_time: runValue.analysis_time as string | null ?? null,
        test_date: runValue.test_date as string | null ?? null,
        test_type: typeof runValue.test_type === "string" ? runValue.test_type : null,
        test_standard: typeof runValue.test_standard === "string" ? runValue.test_standard : null,
        operator: typeof runValue.operator === "string" ? runValue.operator : null,
        machine: typeof runValue.machine === "string" ? runValue.machine : null,
        load_cell: typeof runValue.load_cell === "string" ? runValue.load_cell : null,
        sensor_source: runValue.sensor_source as SensorSource,
        sensor_source_description: typeof runValue.sensor_source_description === "string" ? runValue.sensor_source_description : null,
        compliance_correction: {
          method: correction.method as ComplianceMethod,
          compliance_mm_per_n: isFiniteNumber(correction.compliance_mm_per_n) ? correction.compliance_mm_per_n : null,
          calibration_source: typeof correction.calibration_source === "string" ? correction.calibration_source : null,
          notes: typeof correction.notes === "string" ? correction.notes : null,
        },
        input_file: inputFile,
        columns,
        rows,
        settings: parseScalarRecord(runValue.settings ?? {}, "test settings"),
        result,
      };
    });
    if (testRuns.filter((run) => run.primary_for_reduction).length > 1) {
      throw new Error("A specimen can have at most one primary test run for reduction.");
    }
    return {
      id: specimenValue.id,
      label: specimenValue.label,
      configuration_id: specimenValue.configuration_id,
      geometry,
      print_metadata: parsePrintMetadata(specimenValue.print_metadata),
      test_runs: testRuns,
    };
  });
  const controlledPrintFields: Array<[keyof StudyConfiguration, keyof PrintMetadata]> = [
    ["material", "material"],
    ["manufacturer", "manufacturer"],
    ["material_lot", "material_lot"],
    ["printer", "printer"],
    ["nozzle", "nozzle"],
    ["nozzle_diameter_mm", "nozzle_diameter_mm"],
    ["layer_height_mm", "layer_height_mm"],
    ["raster_strategy", "raster_orientation"],
    ["infill_percent", "infill_percent"],
    ["nozzle_temperature_c", "nozzle_temperature_c"],
    ["bed_temperature_c", "bed_temperature_c"],
  ];
  for (const configuration of configurations) {
    const group = specimens.filter((specimen) => specimen.configuration_id === configuration.id);
    for (const [configurationField, specimenField] of controlledPrintFields) {
      const observed = [...new Set(group
        .map((specimen) => specimen.print_metadata[specimenField])
        .filter((item) => item !== null && item !== ""))];
      const configured = configuration[configurationField] as string | number | null;
      if (configured !== null && observed.some((item) => item !== configured)) {
        throw new Error(`Specimen print metadata conflicts with configuration ${configuration.id}.`);
      }
      if (observed.length > 1) {
        throw new Error(`Incompatible ${String(configurationField)} values require separate configurations.`);
      }
      if (configured === null && observed.length === 1) {
        Object.assign(configuration, { [configurationField]: observed[0] });
      }
    }
    if (configuration.raster_strategy !== null && configuration.orientation !== null &&
        configuration.raster_strategy !== configuration.orientation) {
      throw new Error(`Configuration ${configuration.id} has conflicting raster strategy values.`);
    }
    const raster = configuration.raster_strategy ?? configuration.orientation;
    if (raster !== null && group.some((specimen) =>
      specimen.print_metadata.raster_orientation !== null && specimen.print_metadata.raster_orientation !== raster,
    )) {
      throw new Error(`Specimen raster strategy conflicts with configuration ${configuration.id}.`);
    }
    if (configuration.raster_strategy === null && raster !== null) configuration.raster_strategy = raster;
    const observedStandards = [...new Set(group.flatMap((specimen) =>
      specimen.test_runs.map((run) => run.test_standard).filter((item): item is string => Boolean(item)),
    ))];
    if (configuration.test_standard_revision !== null &&
        observedStandards.some((item) => item !== configuration.test_standard_revision)) {
      throw new Error(`Test standards conflict with configuration ${configuration.id}.`);
    }
    if (observedStandards.length > 1) throw new Error("Incompatible test standards require separate configurations.");
    if (configuration.test_standard_revision === null && observedStandards.length === 1) {
      configuration.test_standard_revision = observedStandards[0];
    }
    const observedTypes = [...new Set(group.flatMap((specimen) =>
      specimen.test_runs.map((run) => run.test_type).filter((item): item is string => Boolean(item)),
    ))];
    if (configuration.test_type !== null && observedTypes.some((item) => item !== configuration.test_type)) {
      throw new Error(`Test types conflict with configuration ${configuration.id}.`);
    }
    if (observedTypes.length > 1) throw new Error("Incompatible test types require separate configurations.");
    if (configuration.test_type === null && observedTypes.length === 1) configuration.test_type = observedTypes[0];
    for (const specimen of group) {
      Object.assign(specimen.print_metadata, Object.fromEntries(
        controlledPrintFields.map(([, specimenField]) => [specimenField, null]),
      ));
    }
  }
  if (value.id !== undefined && typeof value.id !== "string") throw new Error("The workspace contains an invalid study ID.");
  if (value.revision !== undefined && (!Number.isSafeInteger(value.revision) || Number(value.revision) < 1)) {
    throw new Error("The workspace contains an invalid study revision.");
  }
  if (value.saved_at !== undefined && value.saved_at !== null && !isIsoTimestamp(value.saved_at)) {
    throw new Error("The workspace contains an invalid saved-at timestamp.");
  }
  if (campaign.notes !== undefined && campaign.notes !== null && typeof campaign.notes !== "string" ||
      campaign.created_at !== undefined && campaign.created_at !== null && !isIsoTimestamp(campaign.created_at)) {
    throw new Error("The workspace contains invalid campaign notes or timestamp.");
  }
  return {
    format: "styrkeanalyse-fdm-study",
    version: 3,
    id: value.id as string | undefined,
    revision: value.revision as number | undefined,
    saved_at: (value.saved_at ?? undefined) as string | undefined,
    study_name: value.study_name,
    campaign: {
      id: campaign.id,
      name: campaign.name,
      reduction_run_id: typeof campaign.reduction_run_id === "string" ? campaign.reduction_run_id : null,
      notes: campaign.notes as string | null | undefined ?? null,
      created_at: campaign.created_at as string | null | undefined ?? null,
      configurations,
    },
    specimens,
  };
}

function migrateV1(workspace: Record<string, unknown>): StudyWorkspace {
  onlyKeys(workspace, legacyTopLevelKeys, "legacy workspace");
  if (
    !Array.isArray(workspace.columns) || !Array.isArray(workspace.rows) ||
    typeof workspace.study_name !== "string" || typeof workspace.source_file_name !== "string"
  ) {
    throw new Error("This is not a supported StyrkeAnalyse study workspace.");
  }
  if (
    workspace.id !== undefined && typeof workspace.id !== "string" ||
    workspace.revision !== undefined && (!Number.isSafeInteger(workspace.revision) || Number(workspace.revision) < 1) ||
    workspace.saved_at !== undefined && !isIsoTimestamp(workspace.saved_at) ||
    workspace.analysis_time !== undefined && workspace.analysis_time !== "" && !isIsoTimestamp(workspace.analysis_time) ||
    !workspace.study_name.trim() || workspace.study_name.length > 200 || workspace.source_file_name.length > 255
  ) {
    throw new Error("The legacy workspace contains invalid study metadata.");
  }
  const columns = parseColumns(workspace.columns, "legacy columns");
  const rows = parseRows(workspace.rows, "legacy measurement rows");
  const columnSet = new Set(columns);
  if (columns.length === 0 || rows.length === 0 || rows.some((row) =>
    Object.keys(row).length !== columns.length || Object.keys(row).some((key) => !columnSet.has(key)),
  )) {
    throw new Error("Legacy test rows must contain exactly the named columns and at least one measurement.");
  }
  const settings = parseScalarRecord(workspace.settings ?? {}, "legacy settings");
  const result = parseAnalysisResult(workspace.result);
  const dimension = (key: string): number | null => {
    const raw = settings[key];
    if (raw === undefined || raw === null || raw === "") return null;
    if (typeof raw === "boolean") throw new Error(`Legacy specimen dimension ${key} must be numeric.`);
    const value = Number(raw);
    if (!Number.isFinite(value) || value <= 0) {
      throw new Error(`Legacy specimen dimension ${key} must be finite and positive.`);
    }
    return value;
  };
  const sourceName = workspace.source_file_name.trim() || "Unknown legacy input file";
  const migrated: StudyWorkspace = {
    format: "styrkeanalyse-fdm-study",
    version: 3,
    id: typeof workspace.id === "string" ? workspace.id : undefined,
    revision: Number.isSafeInteger(workspace.revision) && Number(workspace.revision) >= 1
      ? Number(workspace.revision)
      : undefined,
    saved_at: typeof workspace.saved_at === "string" ? workspace.saved_at : undefined,
    study_name: workspace.study_name,
    campaign: {
      id: "legacy-campaign",
      name: workspace.study_name,
      reduction_run_id: null,
      notes: null,
      created_at: null,
      configurations: [{
        id: "legacy-configuration",
        label: "Legacy configuration",
        material: null,
        manufacturer: null,
        material_lot: null,
        printer: null,
        print_profile: null,
        nozzle: null,
        nozzle_diameter_mm: null,
        layer_height_mm: null,
        orientation: null,
        build_orientation: null,
        raster_strategy: null,
        infill_percent: null,
        nozzle_temperature_c: null,
        bed_temperature_c: null,
        nominal_geometry: null,
        test_type: null,
        test_standard_revision: null,
      }],
    },
    specimens: [{
      id: "legacy-specimen",
      label: "Legacy specimen",
      configuration_id: "legacy-configuration",
      geometry: {
        width_mm: dimension("widthMm"),
        thickness_mm: dimension("thicknessMm"),
        gauge_length_mm: dimension("gaugeLengthMm"),
      },
      print_metadata: Object.fromEntries(printMetadataKeys.map((key) => [key, null])) as unknown as PrintMetadata,
      test_runs: [{
        id: "legacy-test-run",
        run_id: null,
        primary_for_reduction: true,
        analysis_time: typeof workspace.analysis_time === "string" ? workspace.analysis_time : null,
        test_date: null,
        test_type: null,
        test_standard: null,
        operator: null,
        machine: null,
        load_cell: null,
        sensor_source: "unknown",
        sensor_source_description: null,
        compliance_correction: {
          method: "unknown",
          compliance_mm_per_n: null,
          calibration_source: null,
          notes: null,
        },
        input_file: {
          filename: sourceName,
          media_type: null,
          size_bytes: null,
          sha256: null,
          imported_at: null,
          status: "unavailable_legacy",
        },
        columns,
        rows,
        settings,
        result,
      }],
    }],
  };
  return parseV2(migrated as unknown as Record<string, unknown>);
}

function closeEnough(left: number, right: number): boolean {
  return Math.abs(left - right) <= 1e-9 * Math.max(1, Math.abs(left), Math.abs(right));
}

export function parseWorkspaceText(text: string): StudyWorkspace {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    throw new Error("This is not valid JSON.");
  }
  if (!isRecord(value) || value.format !== "styrkeanalyse-fdm-study") {
    throw new Error("This is not a supported StyrkeAnalyse study workspace.");
  }
  if (value.version === 1) return migrateV1(value);
  if (value.version !== 2 && value.version !== 3) {
    throw new Error("This is not a supported StyrkeAnalyse study workspace.");
  }
  return parseV2(value);
}
