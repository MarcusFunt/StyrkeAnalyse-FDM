import { lazy, Suspense, useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent, type ReactNode } from "react";
import type { EChartsOption } from "echarts";
import Papa from "papaparse";
import {
  Activity,
  ArrowDownToLine,
  ArrowRight,
  BarChart3,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  ClipboardList,
  Database,
  FileUp,
  FlaskConical,
  FolderOpen,
  Gauge,
  Info,
  LoaderCircle,
  Save,
  Settings2,
  Upload,
} from "lucide-react";
import { parseCsvText, type CsvRow } from "./lib/csv";
import {
  analysisInputFingerprint,
  areColumnsMapped,
  areDimensionsValid,
  guessColumn,
  isAnalysisInputValid,
  isAnalysisSnapshotCurrent,
} from "./lib/analysisReadiness";
import {
  parseWorkspaceText,
  type AnalysisResponse,
  type ComplianceMethod,
  type InputFileProvenance,
  type PrintMetadata,
  type SensorSource,
  type StudyWorkspace,
} from "./lib/workspace";

const ResultsChart = lazy(() => import("./ResultsChart"));

type Page = "overview" | "data" | "results";
type ApiState = "checking" | "ready" | "offline";
type ForceUnit = "N" | "kN";
type DisplacementUnit = "mm" | "cm";
type TensionDirection = "positive" | "negative";

interface Settings {
  forceColumn: string;
  displacementColumn: string;
  forceUnit: ForceUnit;
  displacementUnit: DisplacementUnit;
  decimalSeparator: "." | ",";
  tensionDirection: TensionDirection;
  widthMm: string;
  thicknessMm: string;
  gaugeLengthMm: string;
}

interface DesktopStudy {
  id: string;
  revision: number;
  study_name: string;
  source_file_name: string;
  saved_at: string;
  analysis_time: string;
}

interface TrashedStudy extends DesktopStudy {
  deleted_at: string;
  expires_at: string;
}

interface CampaignReductionResponse {
  campaign_name: string;
  configurations: Array<{
    configuration_id: string;
    configuration_label: string;
    specimen_reductions: Array<{
      specimen_id: string;
      modulus_mpa: number | null;
      status: string;
      reason: string | null;
    }>;
    aggregate: {
      n_total: number;
      n_valid: number;
      mean_mpa: number | null;
      sample_standard_deviation_mpa: number | null;
      coefficient_of_variation_percent: number | null;
      minimum_specimens: number;
      maximum_cv_percent: number;
      replicate_ready?: boolean;
      ready_for_validation?: boolean;
      reason: string | null;
    };
  }>;
}

const initialSettings: Settings = {
  forceColumn: "",
  displacementColumn: "",
  forceUnit: "N",
  displacementUnit: "mm",
  decimalSeparator: ".",
  tensionDirection: "positive",
  widthMm: "",
  thicknessMm: "",
  gaugeLengthMm: "",
};

function formatNumber(value: number, maximumFractionDigits = 2): string {
  return new Intl.NumberFormat("en-GB", { maximumFractionDigits }).format(value);
}

function downloadFile(name: string, body: string, type: string): void {
  const url = URL.createObjectURL(new Blob([body], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function asString(value: unknown, fallback: string): string {
  return typeof value === "string" ? value : fallback;
}

function asUnit<T extends string>(value: unknown, allowed: readonly T[], fallback: T): T {
  return typeof value === "string" && allowed.includes(value as T) ? (value as T) : fallback;
}

interface RunnerJobEnvelope {
  job?: {
    id?: unknown;
    status?: unknown;
    error?: unknown;
  };
  run?: {
    id?: unknown;
    created_at?: unknown;
  };
  result?: Record<string, unknown>;
  error?: unknown;
}

async function submitRunAndWait(
  requestBody: Record<string, unknown>,
  failureMessage: string,
): Promise<RunnerJobEnvelope> {
  const response = await fetch("/api/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(requestBody),
  });
  const queued = await response.json() as RunnerJobEnvelope;
  if (!response.ok) {
    throw new Error(typeof queued.error === "string" ? queued.error : failureMessage);
  }
  const jobId = queued.job?.id;
  if (typeof jobId !== "string") throw new Error("The runner did not return a job ID.");

  // The browser never holds a long-lived solver request open. FEM/RVE stages may
  // take minutes or hours; polling keeps the control plane responsive.
  for (let attempt = 0; attempt < 7200; attempt += 1) {
    const statusResponse = await fetch(`/api/jobs/${jobId}`);
    const payload = await statusResponse.json() as RunnerJobEnvelope;
    if (!statusResponse.ok) {
      throw new Error(typeof payload.error === "string" ? payload.error : failureMessage);
    }
    if (payload.job?.status === "succeeded") {
      if (!payload.run || !payload.result) {
        throw new Error("The completed runner job omitted its immutable Run result.");
      }
      return payload;
    }
    if (payload.job?.status === "failed") {
      const detail = payload.job?.error;
      throw new Error(typeof detail === "string" ? detail : failureMessage);
    }
    await new Promise((resolve) => window.setTimeout(resolve, 250));
  }
  throw new Error("The runner job did not finish within 30 minutes.");
}

export default function App() {
  const [page, setPage] = useState<Page>("overview");
  const [apiState, setApiState] = useState<ApiState>("checking");
  const [studyName, setStudyName] = useState("FDM tensile study");
  const [sourceFileName, setSourceFileName] = useState("");
  const [columns, setColumns] = useState<string[]>([]);
  const [rows, setRows] = useState<CsvRow[]>([]);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [settings, setSettings] = useState<Settings>(initialSettings);
  const [specimenMetadata, setSpecimenMetadata] = useState<SpecimenMetadata>(emptySpecimenMetadata);
  const [inputFile, setInputFile] = useState<InputFileProvenance | null>(null);
  const [inputCsvBase64, setInputCsvBase64] = useState<string | null>(null);
  const [analysis, setAnalysis] = useState<AnalysisResponse | null>(null);
  const [analysisRunId, setAnalysisRunId] = useState<string | null>(null);
  const [analysisTime, setAnalysisTime] = useState("");
  const [studyRevision, setStudyRevision] = useState<number | null>(null);
  const [campaignReduction, setCampaignReduction] = useState<CampaignReductionResponse | null>(null);
  const [campaignRunId, setCampaignRunId] = useState<string | null>(null);
  const [isReducingCampaign, setIsReducingCampaign] = useState(false);
  const [serverStudyId, setServerStudyId] = useState("");
  const [workspaceTemplate, setWorkspaceTemplate] = useState<StudyWorkspace | null>(null);
  const [serverStudies, setServerStudies] = useState<DesktopStudy[]>([]);
  const [trashedStudies, setTrashedStudies] = useState<TrashedStudy[]>([]);
  const [retentionDays, setRetentionDays] = useState(30);
  const [showDesktopStudies, setShowDesktopStudies] = useState(false);
  const [saveConflict, setSaveConflict] = useState<{ draft: StudyWorkspace; currentRevision: number; currentSavedAt: string } | null>(null);
  const [permanentDeleteId, setPermanentDeleteId] = useState<string | null>(null);
  const [isSavingDesktop, setIsSavingDesktop] = useState(false);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [message, setMessage] = useState("");
  const csvInput = useRef<HTMLInputElement>(null);
  const workspaceInput = useRef<HTMLInputElement>(null);
  const analysisInputFingerprintRef = useRef("");
  const currentAnalysisFingerprint = analysisInputFingerprint({
    rows,
    columns,
    settings,
    inputSha256: inputFile?.sha256 ?? null,
    specimenId: specimenMetadata.specimenId,
    reductionMetadata: {
      sensorSource: specimenMetadata.sensorSource,
      complianceMethod: specimenMetadata.complianceMethod,
      complianceMmPerN: specimenMetadata.complianceMmPerN,
      calibrationSource: specimenMetadata.calibrationSource,
    },
  });
  analysisInputFingerprintRef.current = currentAnalysisFingerprint;

  useEffect(() => {
    fetch("/api/health")
      .then((response) => {
        if (!response.ok) throw new Error("API unavailable");
        return response.json();
      })
      .then(() => setApiState("ready"))
      .catch(() => setApiState("offline"));
  }, []);

  useEffect(() => {
    if (page !== "results" || apiState !== "ready") return;
    let active = true;

    if (campaignRunId !== null) {
      if (campaignReduction !== null) return;
      setIsReducingCampaign(true);
      void (async () => {
        const response = await fetch(`/api/runs/${campaignRunId}`);
        const payload = await response.json() as RunnerJobEnvelope;
        if (!response.ok) {
          throw new Error(typeof payload.error === "string"
            ? payload.error
            : "Could not load the saved campaign Run.");
        }
        if (!payload.result) throw new Error("The saved campaign Run has no result artifact.");
        if (!active) return;
        setCampaignReduction(payload.result as unknown as CampaignReductionResponse);
      })()
        .catch((error: unknown) => {
          if (!active) return;
          setCampaignReduction(null);
          setCampaignRunId(null);
          setMessage(error instanceof Error ? error.message : "Could not load the saved campaign Run.");
        })
        .finally(() => {
          if (active) setIsReducingCampaign(false);
        });
      return () => {
        active = false;
      };
    }

    const workspace = createWorkspace();
    workspace.campaign.reduction_run_id = null;
    setIsReducingCampaign(true);
    void (async () => {
      const workspaceBytes = new TextEncoder().encode(JSON.stringify(workspace));
      const sourceSha256 = await hashBytes(
        workspaceBytes.buffer.slice(workspaceBytes.byteOffset, workspaceBytes.byteOffset + workspaceBytes.byteLength),
      );
      const upstreamRunIds = workspace.specimens
        .flatMap((specimen) =>
          specimen.test_runs
            .filter((run) => run.primary_for_reduction)
            .map((run) => run.run_id),
        )
        .filter((runId): runId is string => Boolean(runId));
      if (upstreamRunIds.length === 0) {
        throw new Error(
          "Campaign reduction needs at least one local immutable specimen Run. " +
          "Portable workspace exports intentionally detach desktop-local Run IDs.",
        );
      }
      const payload = await submitRunAndWait(
        {
          operation: "campaign",
          input_file: {
            filename: `${workspace.study_name || "study"}.fdmstudy.json`,
            media_type: "application/json",
            sha256: sourceSha256,
            content_base64: arrayBufferToBase64(workspaceBytes.buffer.slice(
              workspaceBytes.byteOffset,
              workspaceBytes.byteOffset + workspaceBytes.byteLength,
            )),
          },
          parameters: {},
          upstream_run_ids: upstreamRunIds,
        },
        "Could not reduce the campaign specimens.",
      );
      if (!active) return;
      if (!payload.result) throw new Error("The completed campaign job omitted its result.");
      setCampaignReduction(payload.result as unknown as CampaignReductionResponse);
      const runId = payload.run?.id;
      if (typeof runId === "string") {
        setCampaignRunId(runId);
        setWorkspaceTemplate((current) => current ? {
          ...current,
          campaign: { ...current.campaign, reduction_run_id: runId },
        } : current);
      }
    })()
      .catch((error: unknown) => {
        if (!active) return;
        setCampaignReduction(null);
        setMessage(error instanceof Error ? error.message : "Could not reduce the campaign specimens.");
      })
      .finally(() => {
        if (active) setIsReducingCampaign(false);
      });
    return () => {
      active = false;
    };
  }, [page, apiState, campaignRunId, campaignReduction]);

  const setupValid = isAnalysisInputValid(
    columns,
    settings.forceColumn,
    settings.displacementColumn,
    settings.widthMm,
    settings.thicknessMm,
    settings.gaugeLengthMm,
  );
  const columnsMapped = areColumnsMapped(columns, settings.forceColumn, settings.displacementColumn);
  const dimensionsValid = areDimensionsValid(
    settings.widthMm,
    settings.thicknessMm,
    settings.gaugeLengthMm,
  );
  const canAnalyze =
    rows.length > 0 &&
    inputCsvBase64 !== null &&
    setupValid &&
    apiState === "ready" &&
    !isAnalyzing;

  const forceChart = useMemo<EChartsOption>(() => {
    if (!analysis) return {};
    return {
      animation: false,
      color: ["#146d72"],
      grid: { left: 58, right: 20, top: 24, bottom: 58 },
      tooltip: { trigger: "axis", valueFormatter: (value) => `${formatNumber(Number(value), 3)} N` },
      xAxis: {
        type: "value",
        name: "Extension (mm)",
        nameLocation: "middle",
        nameGap: 34,
        axisLine: { lineStyle: { color: "#b9c4cf" } },
        splitLine: { lineStyle: { color: "#edf1f4" } },
      },
      yAxis: {
        type: "value",
        name: "Force (N)",
        axisLine: { show: false },
        splitLine: { lineStyle: { color: "#edf1f4" } },
      },
      dataZoom: [{ type: "inside" }, { type: "slider", height: 16, bottom: 8, borderColor: "#e4e9ee" }],
      series: [
        {
          type: "line",
          name: "Tensile force",
          data: analysis.points.map((point) => [point.extension_mm, point.force_n]),
          showSymbol: false,
          lineStyle: { width: 2.5 },
          emphasis: { focus: "series" },
        },
      ],
    };
  }, [analysis]);

  const stressChart = useMemo<EChartsOption>(() => {
    if (!analysis) return {};
    return {
      animation: false,
      color: ["#b66b32"],
      grid: { left: 58, right: 20, top: 24, bottom: 58 },
      tooltip: { trigger: "axis", valueFormatter: (value) => `${formatNumber(Number(value), 4)} MPa` },
      xAxis: {
        type: "value",
        name: "Engineering strain (%)",
        nameLocation: "middle",
        nameGap: 34,
        axisLine: { lineStyle: { color: "#b9c4cf" } },
        splitLine: { lineStyle: { color: "#edf1f4" } },
      },
      yAxis: {
        type: "value",
        name: "Nominal stress (MPa)",
        axisLine: { show: false },
        splitLine: { lineStyle: { color: "#edf1f4" } },
      },
      dataZoom: [{ type: "inside" }, { type: "slider", height: 16, bottom: 8, borderColor: "#e4e9ee" }],
      series: [
        {
          type: "line",
          name: "Nominal stress",
          data: analysis.points.map((point) => [point.strain * 100, point.stress_mpa]),
          showSymbol: false,
          lineStyle: { width: 2.5 },
          emphasis: { focus: "series" },
        },
      ],
    };
  }, [analysis]);

  function setSetting<K extends keyof Settings>(key: K, value: Settings[K]): void {
    setSettings((current) => ({ ...current, [key]: value }));
    setAnalysis(null);
    setAnalysisRunId(null);
    setCampaignRunId(null);
    setCampaignReduction(null);
  }

  async function loadCsv(file: File): Promise<void> {
    setMessage("");
    if (file.size > 12 * 1024 * 1024) {
      setMessage("This file is larger than 12 MB. Split it into smaller test files and import one at a time.");
      return;
    }
    try {
      const bytes = await file.arrayBuffer();
      const parsed = parseCsvText(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
      const sha256 = await hashBytes(bytes);
      const mediaType = file.type || (file.name.toLowerCase().endsWith(".tsv") ? "text/tab-separated-values" : "text/csv");
      setSourceFileName(file.name);
      setInputCsvBase64(arrayBufferToBase64(bytes));
      setInputFile({
        filename: file.name,
        media_type: mediaType,
        size_bytes: file.size,
        sha256,
        imported_at: new Date().toISOString(),
        status: "verified",
      });
      setColumns(parsed.columns);
      setRows(parsed.rows);
      setWarnings(parsed.warnings);
      setAnalysis(null);
      setAnalysisRunId(null);
      setCampaignRunId(null);
      setCampaignReduction(null);
      setSettings((current) => ({
        ...current,
        forceColumn: guessColumn(parsed.columns, /force|load|kraft/i),
        displacementColumn: guessColumn(parsed.columns, /displacement|extension|travel|deflection|weg/i),
      }));
      setPage("data");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not read this file.");
    }
  }

  function applyWorkspace(workspace: StudyWorkspace, selectedSpecimenId?: string): void {
    setWorkspaceTemplate(workspace);
    const specimen = workspace.specimens.find((item) => item.id === selectedSpecimenId) ?? workspace.specimens[0];
    const testRun = specimen.test_runs.find((run) => run.primary_for_reduction) ?? specimen.test_runs[0];
    const configuration = workspace.campaign.configurations.find(
      (item) => item.id === specimen.configuration_id,
    );
    setStudyName(workspace.study_name);
    setServerStudyId(workspace.id ?? "");
    setStudyRevision(workspace.revision ?? null);
    setSourceFileName(testRun?.input_file.filename ?? "");
    setInputFile(testRun?.input_file ?? null);
    setInputCsvBase64(null);
    setColumns(testRun?.columns ?? []);
    setRows(testRun?.rows ?? []);
    setSettings({
      ...initialSettings,
      forceColumn: asString(testRun?.settings.forceColumn, ""),
      displacementColumn: asString(testRun?.settings.displacementColumn, ""),
      forceUnit: asUnit<ForceUnit>(testRun?.settings.forceUnit, ["N", "kN"], "N"),
      displacementUnit: asUnit<DisplacementUnit>(testRun?.settings.displacementUnit, ["mm", "cm"], "mm"),
      decimalSeparator: asUnit<"." | ",">(testRun?.settings.decimalSeparator, [".", ","], "."),
      tensionDirection: asUnit<TensionDirection>(testRun?.settings.tensionDirection, ["positive", "negative"], "positive"),
      widthMm: specimen.geometry.width_mm === null ? "" : String(specimen.geometry.width_mm),
      thicknessMm: specimen.geometry.thickness_mm === null ? "" : String(specimen.geometry.thickness_mm),
      gaugeLengthMm: specimen.geometry.gauge_length_mm === null ? "" : String(specimen.geometry.gauge_length_mm),
    });
    setAnalysis(testRun?.result ?? null);
    setAnalysisRunId(testRun?.run_id ?? null);
    setCampaignRunId(workspace.campaign.reduction_run_id ?? null);
    setCampaignReduction(null);
    setAnalysisTime(testRun?.analysis_time ?? "");
    setSpecimenMetadata({
      campaignId: workspace.campaign.id,
      configurationId: specimen.configuration_id,
      specimenId: specimen.id,
      testRunId: testRun?.id ?? newId("test-run"),
      specimenLabel: specimen.label,
      configurationLabel: configuration?.label ?? "Configuration 1",
      sensorSource: testRun?.sensor_source ?? "unknown",
      sensorSourceDescription: testRun?.sensor_source_description ?? "",
      testDate: testRun?.test_date ?? "",
      testStandard: configuration?.test_standard_revision ?? testRun?.test_standard ?? "",
      operator: testRun?.operator ?? "",
      machine: testRun?.machine ?? "",
      loadCell: testRun?.load_cell ?? "",
      complianceMethod: testRun?.compliance_correction.method ?? "unknown",
      complianceMmPerN: testRun?.compliance_correction.compliance_mm_per_n === null || testRun?.compliance_correction.compliance_mm_per_n === undefined ? "" : String(testRun.compliance_correction.compliance_mm_per_n),
      calibrationSource: testRun?.compliance_correction.calibration_source ?? "",
      print: {
        material: configuration?.material ?? "",
        manufacturer: configuration?.manufacturer ?? specimen.print_metadata.manufacturer ?? "",
        materialLot: configuration?.material_lot ?? "",
        printer: configuration?.printer ?? "",
        nozzle: configuration?.nozzle ?? "",
        nozzleDiameterMm: configuration?.nozzle_diameter_mm === null || configuration?.nozzle_diameter_mm === undefined ? "" : String(configuration.nozzle_diameter_mm),
        layerHeightMm: configuration?.layer_height_mm === null || configuration?.layer_height_mm === undefined ? "" : String(configuration.layer_height_mm),
        rasterOrientation: configuration?.raster_strategy ?? configuration?.orientation ?? "",
        infillPercent: configuration?.infill_percent === null || configuration?.infill_percent === undefined ? "" : String(configuration.infill_percent),
        nozzleTemperatureC: configuration?.nozzle_temperature_c === null || configuration?.nozzle_temperature_c === undefined ? "" : String(configuration.nozzle_temperature_c),
        bedTemperatureC: configuration?.bed_temperature_c === null || configuration?.bed_temperature_c === undefined ? "" : String(configuration.bed_temperature_c),
        printDate: specimen.print_metadata.print_date ?? "",
        gcodeSha256: specimen.print_metadata.gcode_sha256 ?? "",
      },
    });
    setWarnings([]);
    setPage("overview");
  }

  function addAnotherSpecimen(): void {
    const snapshot = createWorkspace();
    const nextNumber = snapshot.specimens.length + 1;
    setWorkspaceTemplate(snapshot);
    setSpecimenMetadata((current) => ({
      ...current,
      specimenId: newId("specimen"),
      testRunId: newId("test-run"),
      specimenLabel: `Specimen ${nextNumber}`,
      testDate: "",
    }));
    setSourceFileName("");
    setInputFile(null);
    setColumns([]);
    setRows([]);
    setWarnings([]);
    setAnalysis(null);
    setAnalysisRunId(null);
    setInputCsvBase64(null);
    setCampaignRunId(null);
    setAnalysisTime("");
    setCampaignReduction(null);
    setSettings((current) => ({
      ...current,
      forceColumn: "",
      displacementColumn: "",
      widthMm: "",
      thicknessMm: "",
      gaugeLengthMm: "",
    }));
    setPage("data");
  }

  function selectCampaignSpecimen(specimenId: string): void {
    applyWorkspace(createWorkspace(), specimenId);
    setCampaignReduction(null);
  }

  async function openWorkspace(file: File): Promise<void> {
    setMessage("");
    if (file.size > 24 * 1024 * 1024) {
      setMessage("This workspace is larger than 24 MB and cannot be opened in the browser.");
      return;
    }
    try {
      applyWorkspace(parseWorkspaceText(await file.text()));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not open this workspace.");
    }
  }

  function createWorkspace(): StudyWorkspace {
    const base = workspaceTemplate;
    const activeSpecimenId = specimenMetadata.specimenId;
    const activeSpecimen = base?.specimens.find((specimen) => specimen.id === activeSpecimenId);
    const printMetadata: PrintMetadata = {
      material: optionalText(specimenMetadata.print.material),
      manufacturer: optionalText(specimenMetadata.print.manufacturer),
      material_lot: optionalText(specimenMetadata.print.materialLot),
      printer: optionalText(specimenMetadata.print.printer),
      nozzle: optionalText(specimenMetadata.print.nozzle),
      nozzle_diameter_mm: optionalNumber(specimenMetadata.print.nozzleDiameterMm),
      layer_height_mm: optionalNumber(specimenMetadata.print.layerHeightMm),
      raster_orientation: optionalText(specimenMetadata.print.rasterOrientation),
      infill_percent: optionalNumber(specimenMetadata.print.infillPercent),
      nozzle_temperature_c: optionalNumber(specimenMetadata.print.nozzleTemperatureC),
      bed_temperature_c: optionalNumber(specimenMetadata.print.bedTemperatureC),
      print_date: optionalDate(specimenMetadata.print.printDate),
      gcode_sha256: optionalText(specimenMetadata.print.gcodeSha256),
    };
    const specimenPrintMetadata: PrintMetadata = {
      ...printMetadata,
      material: null,
      manufacturer: null,
      material_lot: null,
      printer: null,
      nozzle: null,
      nozzle_diameter_mm: null,
      layer_height_mm: null,
      raster_orientation: null,
      infill_percent: null,
      nozzle_temperature_c: null,
      bed_temperature_c: null,
    };
    const geometry = {
      width_mm: optionalNumber(settings.widthMm),
      thickness_mm: optionalNumber(settings.thicknessMm),
      gauge_length_mm: optionalNumber(settings.gaugeLengthMm),
    };
    const fileProvenance: InputFileProvenance = inputFile ?? {
      filename: sourceFileName || "Unknown legacy input file",
      media_type: null,
      size_bytes: null,
      sha256: null,
      imported_at: null,
      status: "unavailable_legacy",
    };
    const testRun = {
      id: specimenMetadata.testRunId,
      run_id: analysisRunId,
      primary_for_reduction: true,
      analysis_time: analysisTime || null,
      test_date: optionalDate(specimenMetadata.testDate),
      test_type: "tensile",
      test_standard: optionalText(specimenMetadata.testStandard),
      operator: optionalText(specimenMetadata.operator),
      machine: optionalText(specimenMetadata.machine),
      load_cell: optionalText(specimenMetadata.loadCell),
      sensor_source: specimenMetadata.sensorSource,
      sensor_source_description: optionalText(specimenMetadata.sensorSourceDescription),
      compliance_correction: {
        method: specimenMetadata.complianceMethod,
        compliance_mm_per_n: specimenMetadata.complianceMethod === "machine_compliance"
          ? optionalNumber(specimenMetadata.complianceMmPerN)
          : null,
        calibration_source: optionalText(specimenMetadata.calibrationSource),
        notes: null,
      },
      input_file: fileProvenance,
      columns,
      rows,
      settings: {
        forceColumn: settings.forceColumn,
        displacementColumn: settings.displacementColumn,
        forceUnit: settings.forceUnit,
        displacementUnit: settings.displacementUnit,
        decimalSeparator: settings.decimalSeparator,
        tensionDirection: settings.tensionDirection,
      },
      result: analysis,
    };
    const activeSpecimenRecord = {
      id: activeSpecimenId,
      label: specimenMetadata.specimenLabel.trim() || "Specimen 1",
      configuration_id: specimenMetadata.configurationId,
      geometry,
      print_metadata: specimenPrintMetadata,
      test_runs: [
        ...(activeSpecimen?.test_runs ?? []).filter((run) => run.id !== specimenMetadata.testRunId),
        ...(sourceFileName || rows.length ? [testRun] : []),
      ],
    };
    const specimenRecords = [
      ...(base?.specimens ?? []).filter((specimen) => specimen.id !== activeSpecimenId),
      activeSpecimenRecord,
    ];
    const previousConfiguration = base?.campaign.configurations.find(
      (configuration) => configuration.id === specimenMetadata.configurationId,
    );
    const configuration = {
      id: specimenMetadata.configurationId,
      label: specimenMetadata.configurationLabel.trim() || "Configuration 1",
      material: printMetadata.material,
      manufacturer: printMetadata.manufacturer,
      material_lot: printMetadata.material_lot,
      printer: printMetadata.printer,
      print_profile: previousConfiguration?.print_profile ?? null,
      nozzle: printMetadata.nozzle,
      nozzle_diameter_mm: printMetadata.nozzle_diameter_mm,
      layer_height_mm: printMetadata.layer_height_mm,
      orientation: previousConfiguration?.orientation ?? null,
      build_orientation: previousConfiguration?.build_orientation ?? null,
      raster_strategy: printMetadata.raster_orientation,
      infill_percent: printMetadata.infill_percent,
      nozzle_temperature_c: printMetadata.nozzle_temperature_c,
      bed_temperature_c: printMetadata.bed_temperature_c,
      nominal_geometry: previousConfiguration?.nominal_geometry ?? null,
      test_type: "tensile",
      test_standard_revision: optionalText(specimenMetadata.testStandard),
    };
    const configurations = [
      ...(base?.campaign.configurations ?? []).filter((item) => item.id !== configuration.id),
      configuration,
    ];
    return {
      format: "styrkeanalyse-fdm-study",
      version: 3,
      id: serverStudyId || undefined,
      revision: studyRevision ?? base?.revision,
      saved_at: new Date().toISOString(),
      study_name: studyName.trim() || "FDM tensile study",
      campaign: {
        id: specimenMetadata.campaignId,
        name: studyName.trim() || "FDM tensile study",
        reduction_run_id: campaignRunId,
        notes: base?.campaign.notes ?? null,
        created_at: base?.campaign.created_at ?? null,
        configurations,
      },
      specimens: specimenRecords,
    };
  }

  function saveWorkspace(): void {
    const workspace = createWorkspace();
    // Formal Run IDs are local references into the desktop artifact store. A
    // portable workspace must not pretend those IDs are resolvable elsewhere.
    const portable: StudyWorkspace = {
      ...workspace,
      campaign: { ...workspace.campaign, reduction_run_id: null },
      specimens: workspace.specimens.map((specimen) => ({
        ...specimen,
        test_runs: specimen.test_runs.map((run) => ({ ...run, run_id: null })),
      })),
    };
    downloadFile(
      `${(studyName.trim() || "fdm-study").toLowerCase().replace(/[^a-z0-9]+/g, "-")}.fdmstudy.json`,
      JSON.stringify(portable, null, 2),
      "application/json",
    );
  }

  async function refreshDesktopStudies(openPanel: boolean): Promise<void> {
    setMessage("");
    try {
      const [activeResponse, trashResponse, retentionResponse] = await Promise.all([
        fetch("/api/studies"),
        fetch("/api/trash"),
        fetch("/api/retention"),
      ]);
      const [active, trash, retention] = await Promise.all([
        activeResponse.json(), trashResponse.json(), retentionResponse.json(),
      ]);
      if (!activeResponse.ok) throw new Error(active.error ?? "Could not read studies saved on this desktop.");
      if (!trashResponse.ok) throw new Error(trash.error ?? "Could not read deleted studies.");
      if (!retentionResponse.ok) throw new Error(retention.error ?? "Could not read the retention policy.");
      setServerStudies(active.studies as DesktopStudy[]);
      setTrashedStudies(trash.studies as TrashedStudy[]);
      setRetentionDays(retention.retention_days as number);
      setShowDesktopStudies(openPanel);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not reach desktop storage.");
      setShowDesktopStudies(false);
    }
  }

  async function saveToDesktop(): Promise<void> {
    if (!rows.length) return;
    setIsSavingDesktop(true);
    setMessage("");
    try {
      const workspace = createWorkspace();
      const url = serverStudyId ? `/api/studies/${serverStudyId}` : "/api/studies";
      let response = await fetch(url, {
        method: serverStudyId ? "PUT" : "POST",
        headers: {
          "Content-Type": "application/json",
          ...(serverStudyId && studyRevision !== null ? { "If-Match": `"${studyRevision}"` } : {}),
        },
        body: JSON.stringify(workspace),
      });
      if (response.status === 404 && serverStudyId) {
        const copy = { ...workspace, id: undefined, revision: undefined };
        response = await fetch("/api/studies", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(copy),
        });
      }
      const payload = await response.json();
      if (response.status === 409) {
        setSaveConflict({
          draft: workspace,
          currentRevision: payload.current_revision as number,
          currentSavedAt: payload.current_saved_at as string,
        });
        return;
      }
      if (!response.ok) throw new Error(payload.error ?? "Could not save this study to the desktop.");
      setServerStudyId(payload.id as string);
      setStudyRevision(payload.revision as number);
      setWorkspaceTemplate({ ...workspace, id: payload.id as string, revision: payload.revision as number });
      await refreshDesktopStudies(showDesktopStudies);
      setMessage("Study saved on the desktop. It will be here when you reconnect.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not save this study to the desktop.");
    } finally {
      setIsSavingDesktop(false);
    }
  }

  async function updateRetentionPolicy(days: number): Promise<void> {
    try {
      const response = await fetch("/api/retention", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ retention_days: days }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error ?? "Could not update study retention.");
      setRetentionDays(payload.retention_days as number);
      await refreshDesktopStudies(true);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not update study retention.");
    }
  }

  async function moveStudyToTrash(study: DesktopStudy): Promise<void> {
    try {
      const response = await fetch(`/api/studies/${study.id}`, {
        method: "DELETE",
        headers: { "If-Match": `"${study.revision}"` },
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error ?? "Could not move study to trash.");
      if (study.id === serverStudyId) {
        setServerStudyId("");
        setStudyRevision(null);
      }
      await refreshDesktopStudies(true);
      setMessage("Study moved to trash. You can restore it during the retention period.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not move study to trash.");
      await refreshDesktopStudies(true);
    }
  }

  async function restoreStudy(study: TrashedStudy): Promise<void> {
    try {
      const response = await fetch(`/api/studies/${study.id}/restore`, {
        method: "POST",
        headers: { "If-Match": `"${study.revision}"` },
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error ?? "Could not restore study.");
      await refreshDesktopStudies(true);
      setMessage("Study restored.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not restore study.");
      await refreshDesktopStudies(true);
    }
  }

  async function permanentlyDeleteStudy(): Promise<void> {
    const study = trashedStudies.find((item) => item.id === permanentDeleteId);
    if (!study) return;
    try {
      const response = await fetch(`/api/studies/${study.id}/permanent`, {
        method: "DELETE",
        headers: { "If-Match": `"${study.revision}"` },
      });
      if (!response.ok) {
        const payload = await response.json();
        throw new Error(payload.error ?? "Could not permanently delete study.");
      }
      setPermanentDeleteId(null);
      await refreshDesktopStudies(true);
      setMessage("Study permanently deleted.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not permanently delete study.");
      await refreshDesktopStudies(true);
    }
  }

  async function saveConflictDraftAsCopy(): Promise<void> {
    if (!saveConflict) return;
    setIsSavingDesktop(true);
    try {
      const copy = { ...saveConflict.draft, id: undefined, revision: undefined };
      const response = await fetch("/api/studies", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(copy),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error ?? "Could not save the local draft as a copy.");
      setServerStudyId(payload.id as string);
      setStudyRevision(payload.revision as number);
      setWorkspaceTemplate({ ...copy, id: payload.id as string, revision: payload.revision as number });
      setSaveConflict(null);
      await refreshDesktopStudies(showDesktopStudies);
      setMessage("The local draft was saved as a separate study.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not save the local draft as a copy.");
    } finally {
      setIsSavingDesktop(false);
    }
  }

  async function openDesktopStudy(studyId: string): Promise<void> {
    setMessage("");
    try {
      const response = await fetch(`/api/studies/${studyId}`);
      const body = await response.text();
      if (!response.ok) {
        const payload = JSON.parse(body) as { error?: string };
        throw new Error(payload.error ?? "Could not open the saved study.");
      }
      applyWorkspace(parseWorkspaceText(body));
      setShowDesktopStudies(false);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not open the saved study.");
    }
  }

  function downloadTemplate(): void {
    downloadFile(
      "fdm-tensile-data-template.csv",
      "specimen_id,force_N,displacement_mm\n",
      "text/csv;charset=utf-8",
    );
  }

  async function runAnalysis(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const submittedFingerprint = currentAnalysisFingerprint;
    setMessage("");
    setCampaignReduction(null);
    setCampaignRunId(null);
    setIsAnalyzing(true);
    try {
      if (!inputCsvBase64 || !inputFile?.sha256) {
        throw new Error("Re-import the original CSV before running a new analysis. Saved workspaces do not include source-file bytes.");
      }
      const payload = await submitRunAndWait(
        {
          operation: "tensile",
          input_file: {
            filename: inputFile.filename,
            media_type: inputFile.media_type ?? "text/csv",
            sha256: inputFile.sha256,
            content_base64: inputCsvBase64,
          },
          parameters: {
            force_column: settings.forceColumn,
            displacement_column: settings.displacementColumn,
            width_mm: Number(settings.widthMm),
            thickness_mm: Number(settings.thicknessMm),
            gauge_length_mm: Number(settings.gaugeLengthMm),
            force_unit: settings.forceUnit,
            displacement_unit: settings.displacementUnit,
            decimal_separator: settings.decimalSeparator,
            tension_direction: settings.tensionDirection,
            specimen_id: specimenMetadata.specimenId,
            sensor_source: specimenMetadata.sensorSource,
            compliance_correction: {
              method: specimenMetadata.complianceMethod,
              compliance_mm_per_n: specimenMetadata.complianceMethod === "machine_compliance"
                ? optionalNumber(specimenMetadata.complianceMmPerN)
                : null,
              calibration_source: optionalText(specimenMetadata.calibrationSource),
            },
          },
        },
        "Analysis failed. Check the mapped columns and units.",
      );
      if (!isAnalysisSnapshotCurrent(submittedFingerprint, analysisInputFingerprintRef.current)) {
        setMessage("The data or setup changed while analysis was running. The stale result was discarded; run it again.");
        return;
      }
      const runId = (payload.run as { id?: unknown } | undefined)?.id;
      const createdAt = (payload.run as { created_at?: unknown } | undefined)?.created_at;
      if (typeof runId !== "string" || !payload.result?.analysis) {
        throw new Error("The runner returned an invalid Run result.");
      }
      setAnalysis(payload.result.analysis as AnalysisResponse);
      setAnalysisRunId(runId);
      setAnalysisTime(typeof createdAt === "string" ? createdAt : new Date().toISOString());
      setPage("results");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not complete the analysis.");
    } finally {
      setIsAnalyzing(false);
    }
  }

  function downloadReducedCsv(): void {
    if (!analysis) return;
    const exported = analysis.points.map((point, index) => ({
      ...rows[index],
      force_N: point.force_n,
      displacement_mm: point.displacement_mm,
      extension_mm: point.extension_mm,
      engineering_strain: point.strain,
      nominal_stress_MPa: point.stress_mpa,
    }));
    downloadFile("fdm-tensile-reduced.csv", Papa.unparse(exported), "text/csv;charset=utf-8");
  }

  function downloadAnalysisJson(): void {
    if (!analysis) return;
    downloadFile(
      "fdm-tensile-analysis.json",
      JSON.stringify(
        {
          format: "styrkeanalyse-fdm-tensile-analysis",
          version: 1,
          created_at: analysisTime,
          source_file_name: sourceFileName,
          settings,
          summary: analysis.summary,
          points: analysis.points,
        },
        null,
        2,
      ),
      "application/json",
    );
  }

  const pageTitle = page === "overview" ? "Study overview" : page === "data" ? "Data & setup" : "Results explorer";
  const campaignSpecimens = createWorkspace().specimens;

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-lockup">
          <div className="brand-mark"><Activity size={19} strokeWidth={2.6} /></div>
          <div><strong>StyrkeAnalyse</strong><span>FDM research workspace</span></div>
        </div>
        <div className="study-switcher">
          <span className="eyebrow">CURRENT STUDY</span>
          <button className="study-button" onClick={() => setPage("overview")}>
            <span className="study-icon"><FlaskConical size={17} /></span>
            <span className="study-name">{studyName}</span>
            <ChevronRight size={15} />
          </button>
        </div>
        <nav className="side-nav" aria-label="Study navigation">
          <span className="eyebrow">WORKSPACE</span>
          <button aria-label="Overview" className={page === "overview" ? "nav-item active" : "nav-item"} onClick={() => setPage("overview")}>
            <Gauge size={17} /><span>Overview</span>
          </button>
          <button aria-label="Data and setup" className={page === "data" ? "nav-item active" : "nav-item"} onClick={() => setPage("data")}>
            <Database size={17} /><span>Data & setup</span>{rows.length > 0 && <span className="nav-count">{rows.length}</span>}
          </button>
          <button aria-label="Results" className={page === "results" ? "nav-item active" : "nav-item"} onClick={() => setPage("results")}>
            <BarChart3 size={17} /><span>Results</span>
          </button>
          <div className="nav-divider" />
          <span className="eyebrow">RESEARCH PIPELINE</span>
          <div className="pipeline-nav-item"><CheckCircle2 size={16} /><span>Baseline tensile</span><span className="ready-dot" /></div>
          <div className="pipeline-nav-item muted"><CircleAlert size={16} /><span>Experimental reduction</span><span className="soon-tag">NEXT</span></div>
          <div className="pipeline-nav-item muted"><CircleAlert size={16} /><span>Finite element models</span><span className="soon-tag">LATER</span></div>
        </nav>
        <div className="sidebar-bottom">
          <div className="local-card">
            <div className="local-icon"><FolderOpen size={16} /></div>
            <div><strong>Desktop workspace</strong><span>Saved studies stay on the host</span></div>
          </div>
          <div className="sidebar-footnote">v0.1 · baseline analysis</div>
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <div className="breadcrumb"><span>STUDIES</span><ChevronRight size={13} /><span>{studyName}</span></div>
          <div className="top-actions">
            <div className={`api-indicator ${apiState}`}>
              <span className="api-dot" />
              {apiState === "ready" ? "Analysis ready" : apiState === "checking" ? "Connecting…" : "Analysis offline"}
            </div>
            <button className="button button-secondary button-small" onClick={() => void refreshDesktopStudies(!showDesktopStudies)}>
              <FolderOpen size={15} /> Open on desktop
            </button>
            <button className="button button-primary button-small" disabled={!rows.length || isSavingDesktop} onClick={() => void saveToDesktop()}>
              <Save size={15} /> {isSavingDesktop ? "Saving…" : "Save on desktop"}
            </button>
            <button className="button button-secondary button-small" onClick={() => workspaceInput.current?.click()}>
              <FolderOpen size={15} /> Open file
            </button>
            <button className="button button-primary button-small" disabled={!rows.length} onClick={saveWorkspace}>
              <Save size={15} /> Export file
            </button>
            {showDesktopStudies && (
              <div className="desktop-study-popover" role="region" aria-label="Desktop study storage">
                <div className="desktop-study-heading"><strong>Saved on this desktop</strong><button aria-label="Close saved studies" onClick={() => setShowDesktopStudies(false)}>×</button></div>
                {serverStudies.length === 0 ? <p>No studies saved here yet. Save the current study to keep it on the host.</p> : serverStudies.map((study) => (
                  <div className="desktop-study-row" key={study.id}>
                    <button type="button" className="desktop-study-open" onClick={() => void openDesktopStudy(study.id)}>
                      <span><strong>{study.study_name}</strong><small>{study.source_file_name || "No source file"}</small></span>
                      <small>{new Date(study.saved_at).toLocaleDateString()}</small>
                    </button>
                    <button className="text-button storage-action" aria-label={`Move ${study.study_name} to trash`} onClick={() => void moveStudyToTrash(study)}>Delete</button>
                  </div>
                ))}
                <div className="retention-control">
                  <label htmlFor="retention-days">Keep deleted studies for</label>
                  <select id="retention-days" value={retentionDays} onChange={(event) => void updateRetentionPolicy(Number(event.target.value))}>
                    {[7, 30, 90, 180, 365, retentionDays].filter((days, index, values) => values.indexOf(days) === index).sort((a, b) => a - b).map((days) => <option value={days} key={days}>{days} days</option>)}
                  </select>
                </div>
                <div className="desktop-study-heading trash-heading"><strong>Trash ({trashedStudies.length})</strong></div>
                {trashedStudies.length === 0 ? <p>Deleted studies appear here until the retention period ends.</p> : trashedStudies.map((study) => (
                  <div className="desktop-study-row trashed-study-row" key={study.id}>
                    <span><strong>{study.study_name}</strong><small>Expires {new Date(study.expires_at).toLocaleDateString()}</small></span>
                    <div className="trash-actions">
                      <button className="text-button storage-action" onClick={() => void restoreStudy(study)}>Restore</button>
                      <button className="text-button storage-action danger-action" onClick={() => setPermanentDeleteId(study.id)}>Delete permanently</button>
                    </div>
                  </div>
                ))}
              </div>
            )}
            <input
              ref={workspaceInput}
              type="file"
              accept=".fdmstudy.json,application/json"
              hidden
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void openWorkspace(file);
                event.currentTarget.value = "";
              }}
            />
          </div>
        </header>

        <div className="page-content">
          <div className="page-heading">
            <div>
              <div className="page-kicker">FDM STRENGTH ANALYSIS</div>
              <h1>{pageTitle}</h1>
              <p>{page === "overview" ? "A clear path from test data to traceable results." : page === "data" ? "Bring in a tensile test, confirm the columns and specimen dimensions." : "Inspect the measured curve and the calculation behind it."}</p>
            </div>
            <div className="heading-state"><span className={rows.length ? "state-check complete" : "state-check"}>{rows.length ? <Check size={13} /> : "1"}</span><span>Data</span><span className="state-line" /><span className={analysis ? "state-check complete" : "state-check"}>{analysis ? <Check size={13} /> : "2"}</span><span>Results</span></div>
          </div>

          {message && <div className="alert-box" role="alert"><CircleAlert size={17} /><span>{message}</span><button aria-label="Dismiss message" onClick={() => setMessage("")}>×</button></div>}

          {page === "overview" && (
            <OverviewPage
              studyName={studyName}
              setStudyName={setStudyName}
              sourceFileName={sourceFileName}
              rowCount={rows.length}
              hasAnalysis={Boolean(analysis)}
              onImport={() => csvInput.current?.click()}
              onData={() => setPage("data")}
              onResults={() => setPage("results")}
              onTemplate={downloadTemplate}
            />
          )}

          {page === "data" && (
            <DataPage
              sourceFileName={sourceFileName}
              columns={columns}
              rows={rows}
              warnings={warnings}
              settings={settings}
              campaignSpecimens={campaignSpecimens}
              activeSpecimenId={specimenMetadata.specimenId}
              onAddSpecimen={addAnotherSpecimen}
              onSelectSpecimen={selectCampaignSpecimen}
              specimenMetadata={specimenMetadata}
              onMetadataChange={(value) => {
                setSpecimenMetadata(value);
                setAnalysis(null);
                setAnalysisRunId(null);
                setCampaignRunId(null);
                setCampaignReduction(null);
              }}
              setSetting={setSetting}
              isDragging={isDragging}
              onFileDrop={(file) => void loadCsv(file)}
              onDragChange={setIsDragging}
              onChooseFile={() => csvInput.current?.click()}
              onTemplate={downloadTemplate}
              onAnalyze={runAnalysis}
              canAnalyze={canAnalyze}
              columnsMapped={columnsMapped}
              dimensionsValid={dimensionsValid}
              isAnalyzing={isAnalyzing}
              apiState={apiState}
              sourceBytesAvailable={inputCsvBase64 !== null}
            />
          )}

          {page === "results" && (
            <ResultsPage
              analysis={analysis}
              analysisRunId={analysisRunId}
              analysisTime={analysisTime}
              sourceFileName={sourceFileName}
              forceChart={forceChart}
              stressChart={stressChart}
              rowCount={rows.length}
              onData={() => setPage("data")}
              onAnalyze={() => setPage("data")}
              onDownloadCsv={downloadReducedCsv}
              onDownloadJson={downloadAnalysisJson}
              campaignReduction={campaignReduction}
              campaignRunId={campaignRunId}
              isReducingCampaign={isReducingCampaign}
            />
          )}

          <input
            ref={csvInput}
            type="file"
            accept=".csv,.tsv,text/csv,text/tab-separated-values"
            hidden
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void loadCsv(file);
              event.currentTarget.value = "";
            }}
          />
        </div>
      </main>
      {saveConflict && (
        <div className="modal-backdrop">
          <section className="confirmation-dialog" role="dialog" tabIndex={-1} aria-modal="true" aria-labelledby="save-conflict-title" aria-describedby="save-conflict-description" onKeyDown={(event) => keepDialogFocus(event, () => setSaveConflict(null))}>
            <div className="section-eyebrow">SAVE CONFLICT</div>
            <h2 id="save-conflict-title">This study changed on another device</h2>
            <p id="save-conflict-description">Your local draft is still open. The desktop has revision {saveConflict.currentRevision}{saveConflict.currentSavedAt ? `, saved ${new Date(saveConflict.currentSavedAt).toLocaleString()}` : ""}.</p>
            <div className="dialog-actions">
              <button className="button button-secondary" autoFocus onClick={() => { const id = serverStudyId; setSaveConflict(null); void openDesktopStudy(id); }}>Reload and discard local draft</button>
              <button className="button button-primary" disabled={isSavingDesktop} onClick={() => void saveConflictDraftAsCopy()}>{isSavingDesktop ? "Saving…" : "Save local draft as a copy"}</button>
              <button className="text-button" onClick={() => setSaveConflict(null)}>Keep working on local draft</button>
            </div>
          </section>
        </div>
      )}
      {permanentDeleteId && (
        <div className="modal-backdrop">
          <section className="confirmation-dialog" role="alertdialog" tabIndex={-1} aria-modal="true" aria-labelledby="permanent-delete-title" aria-describedby="permanent-delete-description" onKeyDown={(event) => keepDialogFocus(event, () => setPermanentDeleteId(null))}>
            <div className="section-eyebrow">PERMANENT DELETION</div>
            <h2 id="permanent-delete-title">Delete this study permanently?</h2>
            <p id="permanent-delete-description">This removes the study and its measurement rows from desktop storage. You cannot restore it afterward.</p>
            <div className="dialog-actions">
              <button className="button button-secondary" autoFocus onClick={() => setPermanentDeleteId(null)}>Cancel</button>
              <button className="button button-danger" onClick={() => void permanentlyDeleteStudy()}>Delete permanently</button>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}

interface OverviewPageProps {
  studyName: string;
  setStudyName: (name: string) => void;
  sourceFileName: string;
  rowCount: number;
  hasAnalysis: boolean;
  onImport: () => void;
  onData: () => void;
  onResults: () => void;
  onTemplate: () => void;
}

function OverviewPage(props: OverviewPageProps) {
  const hasData = props.rowCount > 0;
  return (
    <>
      <section className="overview-intro">
        <div className="intro-copy">
        <div className="intro-overline"><span className="intro-dot" /> DESKTOP RESEARCH WORKSPACE</div>
          <label className="study-title-label" htmlFor="study-name">Study name</label>
          <input id="study-name" className="study-title-input" value={props.studyName} onChange={(event) => props.setStudyName(event.target.value)} />
          <p>Start with your measured tensile data. Each step keeps its units and assumptions visible.</p>
          <div className="intro-actions">
            <button className="button button-light" onClick={hasData ? props.onData : props.onImport}>
              {hasData ? <Settings2 size={16} /> : <FileUp size={16} />}
              {hasData ? "Continue setup" : "Import test data"}<ArrowRight size={15} />
            </button>
            <button className="text-button light-text" onClick={props.onTemplate}><ArrowDownToLine size={15} /> Get CSV template</button>
          </div>
        </div>
        <div className="intro-graphic" aria-hidden="true">
          <div className="graphic-caption">FROM SPECIMEN TO SIGNAL</div>
          <svg viewBox="0 0 360 220" role="presentation">
            <defs><linearGradient id="curveFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#91d5c6" stopOpacity=".28" /><stop offset="1" stopColor="#91d5c6" stopOpacity="0" /></linearGradient></defs>
            <path d="M30 20V184H340" fill="none" stroke="rgba(222,243,241,.28)" strokeWidth="1" />
            <path d="M30 145H340M30 106H340M30 67H340" fill="none" stroke="rgba(222,243,241,.12)" strokeWidth="1" strokeDasharray="4 6" />
            <path d="M30 184C60 183 69 179 91 167C117 152 134 132 158 102C184 69 207 44 234 34C260 24 292 25 330 26V184Z" fill="url(#curveFill)" />
            <path d="M30 184C60 183 69 179 91 167C117 152 134 132 158 102C184 69 207 44 234 34C260 24 292 25 330 26" fill="none" stroke="#91d5c6" strokeWidth="3" strokeLinecap="round" />
            <circle cx="234" cy="34" r="5" fill="#f7c88c" stroke="#173943" strokeWidth="3" />
            <text x="16" y="20" fill="rgba(235,248,246,.58)" fontSize="9">LOAD</text>
            <text x="316" y="206" fill="rgba(235,248,246,.58)" fontSize="9">EXTENSION</text>
          </svg>
          <div className="graphic-note"><span /> Tensile response <small>preview</small></div>
        </div>
      </section>

      <div className="section-title-row"><div><div className="section-eyebrow">YOUR WORKFLOW</div><h2>One step at a time</h2></div><span className="section-side-note">Baseline analysis is available now</span></div>
      <section className="workflow-cards">
        <WorkflowCard number="01" icon={<Database size={18} />} title="Import your measurements" status={hasData ? "complete" : "current"} description={hasData ? `${props.sourceFileName} · ${props.rowCount.toLocaleString()} rows` : "Upload a CSV or TSV from your test rig."} action={hasData ? "Review data" : "Start here"} onClick={props.onData} />
        <WorkflowCard number="02" icon={<Settings2 size={18} />} title="Confirm columns & specimen" status={hasData ? "current" : "locked"} description="Map force and displacement; enter width, thickness and gauge length." action="Configure" onClick={props.onData} />
        <WorkflowCard number="03" icon={<BarChart3 size={18} />} title="Explore the response" status={props.hasAnalysis ? "complete" : "locked"} description={props.hasAnalysis ? "View curves, peak values and downloadable results." : "Review force-extension and stress-strain curves."} action={props.hasAnalysis ? "View results" : "See results"} onClick={props.onResults} />
      </section>

      <section className="capability-strip">
        <div className="capability-icon"><Info size={17} /></div>
        <div><strong>What this version calculates</strong><p>Nominal tensile stress from force and cross-sectional area, plus engineering strain from extension and gauge length. FEM and material-model comparisons will appear here when those workflows are implemented.</p></div>
        <div className="capability-badge"><CheckCircle2 size={14} /> Baseline ready</div>
      </section>
    </>
  );
}

function WorkflowCard(props: { number: string; icon: ReactNode; title: string; description: string; action: string; status: "complete" | "current" | "locked"; onClick: () => void }) {
  return (
    <button className={`workflow-card ${props.status}`} onClick={props.onClick}>
      <div className="workflow-top"><span className="workflow-number">{props.number}</span><span className="workflow-icon">{props.icon}</span>{props.status === "complete" && <CheckCircle2 className="workflow-complete" size={17} />}</div>
      <strong>{props.title}</strong><p>{props.description}</p>
      <span className="workflow-action">{props.action}<ArrowRight size={14} /></span>
    </button>
  );
}

interface DataPageProps {
  sourceBytesAvailable: boolean;
  sourceFileName: string;
  columns: string[];
  rows: CsvRow[];
  warnings: string[];
  settings: Settings;
  campaignSpecimens: StudyWorkspace["specimens"];
  activeSpecimenId: string;
  onAddSpecimen: () => void;
  onSelectSpecimen: (specimenId: string) => void;
  specimenMetadata: SpecimenMetadata;
  onMetadataChange: (metadata: SpecimenMetadata) => void;
  columnsMapped: boolean;
  dimensionsValid: boolean;
  setSetting: <K extends keyof Settings>(key: K, value: Settings[K]) => void;
  isDragging: boolean;
  onFileDrop: (file: File) => void;
  onDragChange: (dragging: boolean) => void;
  onChooseFile: () => void;
  onTemplate: () => void;
  onAnalyze: (event: FormEvent<HTMLFormElement>) => void;
  canAnalyze: boolean;
  isAnalyzing: boolean;
  apiState: ApiState;
}

function DataPage(props: DataPageProps) {
  const isEmpty = props.rows.length === 0;
  const configurationSpecimenCount = props.campaignSpecimens.filter(
    (specimen) => specimen.configuration_id === props.specimenMetadata.configurationId,
  ).length;
  function setMetadata<K extends keyof SpecimenMetadata>(key: K, value: SpecimenMetadata[K]): void {
    props.onMetadataChange({ ...props.specimenMetadata, [key]: value });
  }
  function setPrintMetadata<K extends keyof SpecimenMetadata["print"]>(key: K, value: SpecimenMetadata["print"][K]): void {
    props.onMetadataChange({
      ...props.specimenMetadata,
      print: { ...props.specimenMetadata.print, [key]: value },
    });
  }
  return (
    <div className="data-layout">
      <div className="data-main-column">
        <section className="panel import-panel">
          <div className="panel-heading"><div><div className="section-eyebrow">01 · SOURCE DATA</div><h2>Import a tensile test</h2><p>CSV and tab-separated files are supported in this first version.</p></div>{!isEmpty && <span className="file-chip"><FileUp size={14} />{props.sourceFileName}</span>}</div>
          {isEmpty ? (
            <div
              className={`drop-zone ${props.isDragging ? "dragging" : ""}`}
              onDragEnter={(event) => { event.preventDefault(); props.onDragChange(true); }}
              onDragOver={(event) => { event.preventDefault(); props.onDragChange(true); }}
              onDragLeave={(event) => { event.preventDefault(); props.onDragChange(false); }}
              onDrop={(event) => { event.preventDefault(); props.onDragChange(false); const file = event.dataTransfer.files[0]; if (file) props.onFileDrop(file); }}
            >
              <div className="drop-icon"><Upload size={21} /></div>
              <strong>Drop your test file here</strong>
              <span>CSV or TSV · up to 12 MB</span>
              <button className="button button-secondary" onClick={props.onChooseFile}><FolderOpen size={15} /> Choose file</button>
              <div className="drop-template">Not sure about the format? <button onClick={props.onTemplate}>Download a header template</button></div>
            </div>
          ) : (
            <div className="loaded-file-row">
              <div className="loaded-file-icon"><ClipboardList size={19} /></div>
              <div className="loaded-file-info"><strong>{props.sourceFileName}</strong><span>{props.rows.length.toLocaleString()} measurement rows · {props.columns.length} columns</span></div>
              <span className="loaded-file-state"><CheckCircle2 size={14} /> Imported</span>
              <button className="icon-button" aria-label="Choose a different data file" onClick={props.onChooseFile}><Upload size={16} /></button>
            </div>
          )}
          {props.warnings.length > 0 && <div className="warning-list"><CircleAlert size={16} /><div><strong>Import warnings</strong>{props.warnings.slice(0, 4).map((warning) => <span key={warning}>{warning}</span>)}</div></div>}
        </section>

        <section className="panel campaign-specimens-panel" aria-labelledby="campaign-specimens-title">
          <div className="panel-heading">
            <div><div className="section-eyebrow">CAMPAIGN REPLICATES</div><h2 id="campaign-specimens-title">Specimens in this campaign</h2><p>Each physical specimen counts once; measurement rows are not replicates.</p></div>
            <span className={configurationSpecimenCount >= 5 ? "replicate-count ready" : "replicate-count"}>{configurationSpecimenCount} / 5 minimum</span>
          </div>
          <div className="campaign-specimen-list">
            {props.campaignSpecimens.map((specimen) => {
              const run = specimen.test_runs.find((testRun) => testRun.primary_for_reduction);
              return (
                <button
                  type="button"
                  key={specimen.id}
                  className={specimen.id === props.activeSpecimenId ? "campaign-specimen active" : "campaign-specimen"}
                  aria-pressed={specimen.id === props.activeSpecimenId}
                  onClick={() => props.onSelectSpecimen(specimen.id)}
                >
                  <span><strong>{specimen.label}</strong><small>{run?.input_file.filename ?? "No test file yet"}</small></span>
                  <span className={run?.result ? "specimen-analysis-state complete" : "specimen-analysis-state"}>{run?.result ? "Analysed" : "Needs analysis"}</span>
                </button>
              );
            })}
          </div>
          <button className="text-button add-specimen-button" type="button" disabled={isEmpty} onClick={props.onAddSpecimen}>
            <Upload size={14} /> Add another specimen to this configuration
          </button>
        </section>

        {!isEmpty && (
          <>
            <section className="panel mapping-panel">
              <div className="panel-heading"><div><div className="section-eyebrow">02 · COLUMN MAPPING</div><h2>Tell us what each column means</h2><p>We suggest matches by header name. Check them before continuing.</p></div><div className="step-mini"><span>1</span><span>2</span><span>3</span></div></div>
              <div className="mapping-grid">
                <SelectField label="Force column" value={props.settings.forceColumn} options={props.columns} allowEmpty onChange={(value) => props.setSetting("forceColumn", value)} />
                <SelectField label="Displacement column" value={props.settings.displacementColumn} options={props.columns} allowEmpty onChange={(value) => props.setSetting("displacementColumn", value)} />
                <SelectField label="Force unit" value={props.settings.forceUnit} options={["N", "kN"]} onChange={(value) => props.setSetting("forceUnit", value as ForceUnit)} />
                <SelectField label="Displacement unit" value={props.settings.displacementUnit} options={["mm", "cm"]} onChange={(value) => props.setSetting("displacementUnit", value as DisplacementUnit)} />
                <SelectField label="Decimal separator" value={props.settings.decimalSeparator} options={[".", ","]} onChange={(value) => props.setSetting("decimalSeparator", value as "." | ",")} />
                <SelectField label="Tension is recorded as" value={props.settings.tensionDirection} options={["positive", "negative"]} onChange={(value) => props.setSetting("tensionDirection", value as TensionDirection)} />
              </div>
              <div className="mapping-note"><Info size={15} /><span>Comma decimals are supported for semicolon-separated files. Thousands separators are not assumed.</span></div>
            </section>

            <section className="panel geometry-panel">
              <div className="panel-heading"><div><div className="section-eyebrow">03 · SPECIMEN GEOMETRY</div><h2>Enter the measured dimensions</h2><p>For this baseline, the gauge section is treated as rectangular.</p></div><div className="formula-chip">Area = width × thickness</div></div>
              <div className="geometry-grid">
                <NumberField label="Width" unit="mm" value={props.settings.widthMm} onChange={(value) => props.setSetting("widthMm", value)} />
                <NumberField label="Thickness" unit="mm" value={props.settings.thicknessMm} onChange={(value) => props.setSetting("thicknessMm", value)} />
                <NumberField label="Gauge length" unit="mm" value={props.settings.gaugeLengthMm} onChange={(value) => props.setSetting("gaugeLengthMm", value)} />
                <div className="area-preview"><span>Calculated area</span><strong>{(Number(props.settings.widthMm) * Number(props.settings.thicknessMm) || 0).toLocaleString("en-GB", { maximumFractionDigits: 3 })}<small> mm²</small></strong></div>
              </div>
              <div className="mapping-note"><Info size={15} /><span>Force is converted to newtons and displacement to millimetres before calculation. The first displacement value is treated as the zero point.</span></div>
            </section>

            <section className="panel metadata-panel">
              <details>
                <summary><span><span className="section-eyebrow">04 · TRACEABILITY</span><strong>Campaign, test, and print metadata</strong><small>Record what is known; unknown fields stay explicitly blank.</small></span><ChevronRight size={17} /></summary>
                <div className="metadata-content">
                  <h3>Configuration and specimen</h3>
                  <div className="mapping-grid">
                    <TextField label="Configuration label" value={props.specimenMetadata.configurationLabel} onChange={(value) => setMetadata("configurationLabel", value)} />
                    <TextField label="Specimen ID / label" value={props.specimenMetadata.specimenLabel} onChange={(value) => setMetadata("specimenLabel", value)} />
                  </div>
                  <h3>Test and measurement source</h3>
                  <div className="mapping-grid">
                    <SelectField label="Displacement sensor source" value={props.specimenMetadata.sensorSource} options={["unknown", "extensometer", "crosshead", "clip_gauge", "dic", "other"]} onChange={(value) => setMetadata("sensorSource", value as SensorSource)} />
                    {props.specimenMetadata.sensorSource === "other" && <TextField label="Describe the sensor" value={props.specimenMetadata.sensorSourceDescription} onChange={(value) => setMetadata("sensorSourceDescription", value)} />}
                    <TextField label="Test date" type="date" value={props.specimenMetadata.testDate} onChange={(value) => setMetadata("testDate", value)} />
                    <TextField label="Test standard and revision" value={props.specimenMetadata.testStandard} onChange={(value) => setMetadata("testStandard", value)} />
                    <TextField label="Operator" value={props.specimenMetadata.operator} onChange={(value) => setMetadata("operator", value)} />
                    <TextField label="Test machine" value={props.specimenMetadata.machine} onChange={(value) => setMetadata("machine", value)} />
                    <TextField label="Load cell" value={props.specimenMetadata.loadCell} onChange={(value) => setMetadata("loadCell", value)} />
                    <SelectField label="Compliance correction" value={props.specimenMetadata.complianceMethod} options={["unknown", "not_required", "machine_compliance", "other"]} onChange={(value) => setMetadata("complianceMethod", value as ComplianceMethod)} />
                    {props.specimenMetadata.complianceMethod === "machine_compliance" && <>
                      <TextField label="Compliance (mm/N)" type="number" value={props.specimenMetadata.complianceMmPerN} onChange={(value) => setMetadata("complianceMmPerN", value)} />
                      <TextField label="Calibration source" value={props.specimenMetadata.calibrationSource} onChange={(value) => setMetadata("calibrationSource", value)} />
                    </>}
                  </div>
                  <h3>Print and material</h3>
                  <div className="mapping-grid">
                    <TextField label="Material / polymer" value={props.specimenMetadata.print.material} onChange={(value) => setPrintMetadata("material", value)} />
                    <TextField label="Manufacturer" value={props.specimenMetadata.print.manufacturer} onChange={(value) => setPrintMetadata("manufacturer", value)} />
                    <TextField label="Material lot" value={props.specimenMetadata.print.materialLot} onChange={(value) => setPrintMetadata("materialLot", value)} />
                    <TextField label="Printer" value={props.specimenMetadata.print.printer} onChange={(value) => setPrintMetadata("printer", value)} />
                    <TextField label="Nozzle" value={props.specimenMetadata.print.nozzle} onChange={(value) => setPrintMetadata("nozzle", value)} />
                    <TextField label="Nozzle diameter (mm)" type="number" value={props.specimenMetadata.print.nozzleDiameterMm} onChange={(value) => setPrintMetadata("nozzleDiameterMm", value)} />
                    <TextField label="Layer height (mm)" type="number" value={props.specimenMetadata.print.layerHeightMm} onChange={(value) => setPrintMetadata("layerHeightMm", value)} />
                    <TextField label="Raster / build orientation" value={props.specimenMetadata.print.rasterOrientation} onChange={(value) => setPrintMetadata("rasterOrientation", value)} />
                    <TextField label="Infill (%)" type="number" value={props.specimenMetadata.print.infillPercent} onChange={(value) => setPrintMetadata("infillPercent", value)} />
                    <TextField label="Nozzle temperature (°C)" type="number" value={props.specimenMetadata.print.nozzleTemperatureC} onChange={(value) => setPrintMetadata("nozzleTemperatureC", value)} />
                    <TextField label="Bed temperature (°C)" type="number" value={props.specimenMetadata.print.bedTemperatureC} onChange={(value) => setPrintMetadata("bedTemperatureC", value)} />
                    <TextField label="Print date" type="date" value={props.specimenMetadata.print.printDate} onChange={(value) => setPrintMetadata("printDate", value)} />
                    <TextField label="G-code SHA-256" value={props.specimenMetadata.print.gcodeSha256} onChange={(value) => setPrintMetadata("gcodeSha256", value)} />
                  </div>
                  <div className="mapping-note"><Info size={15} /><span>Imported-file SHA-256, byte size, and import time are captured automatically and saved with this test run.</span></div>
                </div>
              </details>
            </section>

            <section className="panel preview-panel">
              <div className="panel-heading"><div><div className="section-eyebrow">DATA CHECK</div><h2>Preview your measurements</h2><p>Showing the first {Math.min(6, props.rows.length)} of {props.rows.length.toLocaleString()} rows.</p></div><span className="preview-tag"><CheckCircle2 size={14} /> Values preserved as imported</span></div>
              <div className="table-scroll"><table><thead><tr><th>Row</th>{props.columns.map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>{props.rows.slice(0, 6).map((row, index) => <tr key={index}><td className="row-index">{index + 1}</td>{props.columns.map((column) => <td key={column}>{row[column] ?? <span className="missing-value">blank</span>}</td>)}</tr>)}</tbody></table></div>
            </section>
          </>
        )}
      </div>

      <aside className="setup-rail">
        <section className="panel readiness-card">
          <div className="section-eyebrow">ANALYSIS READINESS</div>
          <h3>{isEmpty ? "Waiting for data" : props.canAnalyze ? "Ready to analyse" : "Review setup"}</h3>
          <p>{isEmpty ? "Import a CSV or TSV to start." : "Confirm both columns and the specimen dimensions."}</p>
          {!isEmpty && !props.sourceBytesAvailable && (
            <p className="campaign-reduction-empty">Re-import the original CSV to create a new Run. Saved workspaces retain measurement rows, not the source bytes.</p>
          )}
          <div className="readiness-list">
            <ReadinessItem done={!isEmpty} label="Test file imported" />
            <ReadinessItem done={props.columnsMapped} label="Distinct columns mapped" />
            <ReadinessItem done={props.dimensionsValid} label="Positive dimensions entered" />
            <ReadinessItem done={configurationSpecimenCount >= 5} label="At least five specimens in configuration" />
            <ReadinessItem done={props.apiState === "ready"} label="Analysis service online" />
          </div>
          {!isEmpty && (
            <form onSubmit={props.onAnalyze}>
              <button className="button button-primary button-wide" disabled={!props.canAnalyze}>
                {props.isAnalyzing ? <LoaderCircle className="spin" size={16} /> : <Activity size={16} />}
                {props.isAnalyzing ? "Analysing measurements…" : "Run tensile baseline"}
                {!props.isAnalyzing && <ArrowRight size={15} />}
              </button>
            </form>
          )}
          {props.apiState === "offline" && <div className="offline-hint">Start the GUI and runner services with <code>docker compose up -d gui runner</code>.</div>}
        </section>
        <section className="panel formula-card">
          <div className="formula-icon"><Gauge size={17} /></div>
          <strong>What is calculated</strong>
          <div className="equation">σ = F / A</div>
          <p>Nominal stress uses force divided by the measured cross-sectional area. Engineering strain uses extension divided by gauge length.</p>
          <div className="formula-foot"><span>Stress</span><strong>MPa</strong><span>Strain</span><strong>mm/mm</strong></div>
        </section>
        <div className="privacy-note"><FolderOpen size={15} /><span>Save studies to this desktop to continue from another device on your tailnet.</span></div>
      </aside>
    </div>
  );
}

function SelectField(props: { label: string; value: string; options: string[]; allowEmpty?: boolean; onChange: (value: string) => void }) {
  return <label className="field"><span>{props.label}</span><select value={props.value} onChange={(event) => props.onChange(event.target.value)}>{props.allowEmpty && <option value="">Select a column</option>}{props.options.map((option) => <option value={option} key={option}>{option}</option>)}</select></label>;
}

function TextField(props: { label: string; value: string; type?: "text" | "number" | "date"; onChange: (value: string) => void }) {
  return <label className="field"><span>{props.label}</span><input type={props.type ?? "text"} min={props.type === "number" ? "0" : undefined} step={props.type === "number" ? "any" : undefined} value={props.value} onChange={(event) => props.onChange(event.target.value)} /></label>;
}

interface SpecimenMetadata {
  campaignId: string;
  configurationId: string;
  specimenId: string;
  testRunId: string;
  specimenLabel: string;
  configurationLabel: string;
  sensorSource: SensorSource;
  sensorSourceDescription: string;
  testDate: string;
  testStandard: string;
  operator: string;
  machine: string;
  loadCell: string;
  complianceMethod: ComplianceMethod;
  complianceMmPerN: string;
  calibrationSource: string;
  print: {
    material: string;
    manufacturer: string;
    materialLot: string;
    printer: string;
    nozzle: string;
    nozzleDiameterMm: string;
    layerHeightMm: string;
    rasterOrientation: string;
    infillPercent: string;
    nozzleTemperatureC: string;
    bedTemperatureC: string;
    printDate: string;
    gcodeSha256: string;
  };
}

function newId(prefix: string): string {
  return `${prefix}-${crypto.randomUUID()}`;
}

function keepDialogFocus(event: KeyboardEvent<HTMLElement>, onEscape: () => void): void {
  if (event.key === "Escape") {
    event.preventDefault();
    onEscape();
    return;
  }
  if (event.key !== "Tab") return;

  const focusable = Array.from(
    event.currentTarget.querySelectorAll<HTMLElement>(
      'a[href], button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])',
    ),
  ).filter((element) => element.offsetParent !== null && element.getAttribute("aria-hidden") !== "true");
  if (!focusable.length) {
    event.preventDefault();
    event.currentTarget.focus();
    return;
  }
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && (document.activeElement === first || !focusable.includes(document.activeElement as HTMLElement))) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && (document.activeElement === last || !focusable.includes(document.activeElement as HTMLElement))) {
    event.preventDefault();
    first.focus();
  }
}

function emptySpecimenMetadata(): SpecimenMetadata {
  return {
    campaignId: newId("campaign"),
    configurationId: newId("configuration"),
    specimenId: newId("specimen"),
    testRunId: newId("test-run"),
    specimenLabel: "Specimen 1",
    configurationLabel: "Configuration 1",
    sensorSource: "unknown",
    sensorSourceDescription: "",
    testDate: "",
    testStandard: "",
    operator: "",
    machine: "",
    loadCell: "",
    complianceMethod: "unknown",
    complianceMmPerN: "",
    calibrationSource: "",
    print: {
      material: "",
      manufacturer: "",
      materialLot: "",
      printer: "",
      nozzle: "",
      nozzleDiameterMm: "",
      layerHeightMm: "",
      rasterOrientation: "",
      infillPercent: "",
      nozzleTemperatureC: "",
      bedTemperatureC: "",
      printDate: "",
      gcodeSha256: "",
    },
  };
}

function optionalText(value: string): string | null {
  const trimmed = value.trim();
  return trimmed || null;
}

function optionalNumber(value: string): number | null {
  if (!value.trim()) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function optionalDate(value: string): string | null {
  return /^\d{4}-\d{2}-\d{2}$/.test(value) ? value : null;
}

function hashBytes(bytes: ArrayBuffer): Promise<string> {
  return crypto.subtle.digest("SHA-256", bytes).then((digest) =>
    Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join(""),
  );
}

function arrayBufferToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  const chunkSize = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
  }
  return btoa(binary);
}

function NumberField(props: { label: string; unit: string; value: string; onChange: (value: string) => void }) {
  return <label className="field"><span>{props.label}</span><div className="number-input"><input type="number" min="0.000001" step="any" value={props.value} onChange={(event) => props.onChange(event.target.value)} /><span>{props.unit}</span></div></label>;
}

function ReadinessItem(props: { done: boolean; label: string }) {
  return <div className={props.done ? "readiness-item done" : "readiness-item"}><span>{props.done ? <Check size={11} /> : ""}</span><label>{props.label}</label></div>;
}

interface ResultsPageProps {
  analysis: AnalysisResponse | null;
  analysisRunId: string | null;
  analysisTime: string;
  sourceFileName: string;
  forceChart: EChartsOption;
  stressChart: EChartsOption;
  rowCount: number;
  onData: () => void;
  onAnalyze: () => void;
  onDownloadCsv: () => void;
  onDownloadJson: () => void;
  campaignReduction: CampaignReductionResponse | null;
  campaignRunId: string | null;
  isReducingCampaign: boolean;
}

function ResultsPage(props: ResultsPageProps) {
  if (!props.analysis) {
    return <>
      <div className="empty-results"><div className="empty-results-icon"><BarChart3 size={24} /></div><h2>No result for this specimen yet</h2><p>Import its test data, confirm the columns and dimensions, then run the tensile baseline.</p><button className="button button-primary" onClick={props.onAnalyze}><Settings2 size={15} /> Go to data setup<ArrowRight size={14} /></button></div>
      <CampaignReductionPanel reduction={props.campaignReduction} runId={props.campaignRunId} isLoading={props.isReducingCampaign} />
    </>;
  }
  const summary = props.analysis.summary;
  return (
    <>
      <section className="result-runbar">
        <div className="run-status-icon"><CheckCircle2 size={17} /></div>
        <div><strong>Tensile baseline complete</strong><span>{props.sourceFileName} · {summary.sample_count.toLocaleString()} measurements · {props.analysisTime ? new Date(props.analysisTime).toLocaleString() : ""}</span></div>
        <div className="runbar-actions">{props.analysisRunId && <a className="text-button" href={`/api/runs/${props.analysisRunId}`} target="_blank" rel="noreferrer">Open tensile Run record</a>}<button className="button button-secondary button-small" onClick={props.onDownloadJson}><ArrowDownToLine size={14} /> Analysis JSON</button><button className="button button-secondary button-small" onClick={props.onDownloadCsv}><ArrowDownToLine size={14} /> Reduced CSV</button><button className="icon-button" aria-label="Change analysis setup" onClick={props.onData}><Settings2 size={16} /></button></div>
      </section>

      <div className="result-metrics">
        <MetricCard label="Peak nominal stress" value={formatNumber(summary.peak_stress_mpa, 3)} unit="MPa" note={`At row ${summary.peak_stress_row}`} icon={<Activity size={17} />} accent="teal" />
        <MetricCard label="Peak tensile force" value={formatNumber(summary.peak_force_n, 2)} unit="N" note={`At row ${summary.peak_force_row}`} icon={<Gauge size={17} />} accent="amber" />
        <MetricCard label="Cross-sectional area" value={formatNumber(summary.cross_section_area_mm2, 3)} unit="mm²" note="Width × thickness" icon={<ClipboardList size={17} />} accent="blue" />
        <MetricCard label="Points analysed" value={formatNumber(summary.sample_count, 0)} unit="rows" note={`Gauge length ${formatNumber(summary.gauge_length_mm, 2)} mm`} icon={<Database size={17} />} accent="violet" />
      </div>

      <div className="chart-grid">
        <section className="panel chart-panel">
          <div className="chart-heading"><div><div className="section-eyebrow">MEASURED RESPONSE</div><h2>Force vs. extension</h2><p>Extension is zeroed to the first imported displacement value.</p></div><span className="chart-unit-tag">N · mm</span></div>
          <Suspense fallback={<div className="chart-loading">Loading chart…</div>}>
            <ResultsChart option={props.forceChart} label={`Force versus extension line chart with ${summary.sample_count} points. Peak tensile force ${formatNumber(summary.peak_force_n, 2)} newtons at row ${summary.peak_force_row}. The calculated values table provides a text alternative.`} />
          </Suspense>
        </section>
        <section className="panel chart-panel">
          <div className="chart-heading"><div><div className="section-eyebrow">CALCULATED RESPONSE</div><h2>Nominal stress vs. strain</h2><p>Stress = force / area; strain = extension / gauge length.</p></div><span className="chart-unit-tag">MPa · %</span></div>
          <Suspense fallback={<div className="chart-loading">Loading chart…</div>}>
            <ResultsChart option={props.stressChart} label={`Nominal stress versus engineering strain line chart with ${summary.sample_count} points. Peak nominal stress ${formatNumber(summary.peak_stress_mpa, 3)} megapascals at row ${summary.peak_stress_row}. The calculated values table provides a text alternative.`} />
          </Suspense>
        </section>
      </div>

      <section className="panel result-table-panel">
        <div className="panel-heading"><div><div className="section-eyebrow">REDUCED DATA</div><h2>Calculated values</h2><p>First {Math.min(20, props.analysis.points.length)} of {props.analysis.points.length.toLocaleString()} rows.</p></div><button className="text-button" onClick={props.onDownloadCsv}><ArrowDownToLine size={14} /> Export all rows</button></div>
        <div className="table-scroll"><table><thead><tr><th>Row</th><th>Force (N)</th><th>Displacement (mm)</th><th>Extension (mm)</th><th>Strain (mm/mm)</th><th>Stress (MPa)</th></tr></thead><tbody>{props.analysis.points.slice(0, 20).map((point) => <tr key={point.row_number}><td className="row-index">{point.row_number}</td><td>{formatNumber(point.force_n, 4)}</td><td>{formatNumber(point.displacement_mm, 4)}</td><td>{formatNumber(point.extension_mm, 4)}</td><td>{formatNumber(point.strain, 6)}</td><td className="stress-value">{formatNumber(point.stress_mpa, 4)}</td></tr>)}</tbody></table></div>
      </section>

      <CampaignReductionPanel reduction={props.campaignReduction} runId={props.campaignRunId} isLoading={props.isReducingCampaign} />

      <div className="result-limit-note"><Info size={15} /><span>This is a nominal tensile baseline only. It does not include machine-compliance correction, replicate statistics, material calibration or FEM predictions.</span></div>
    </>
  );
}

function CampaignReductionPanel(props: { reduction: CampaignReductionResponse | null; runId: string | null; isLoading: boolean }) {
  return (
    <section className="panel campaign-reduction-panel" aria-labelledby="campaign-reduction-title">
      <div className="panel-heading">
        <div><div className="section-eyebrow">REPLICATE REDUCTION</div><h2 id="campaign-reduction-title">Campaign modulus summary</h2><p>Project-defined chord modulus over engineering strain 0.0005–0.0025.</p></div>
        <div>{props.isLoading && <span className="reduction-loading" role="status">Reducing specimens…</span>}{props.runId && <a className="text-button" href={`/api/runs/${props.runId}`} target="_blank" rel="noreferrer">Open campaign Run record</a>}</div>
      </div>
      <p className="scientific-caveat">A passing five-specimen and 15% CoV check is campaign readiness only. FEM comparison still requires the separate solver verification gates.</p>
      {!props.reduction ? (
        <p className="campaign-reduction-empty">Campaign reduction is not available yet. Analyse specimens with a recorded extensometer, clip gauge, DIC, or documented crosshead compliance correction.</p>
      ) : props.reduction.configurations.length === 0 ? (
        <p className="campaign-reduction-empty">Add specimens to a configuration to calculate campaign statistics.</p>
      ) : (
        <div className="configuration-reductions">
          {props.reduction.configurations.map((configuration) => {
            const aggregate = configuration.aggregate;
            return (
              <section className="configuration-reduction" key={configuration.configuration_id}>
                <div className="configuration-reduction-heading">
                  <div><h3>{configuration.configuration_label}</h3><span>{aggregate.n_valid} valid of {aggregate.n_total} specimens</span></div>
                  <span className={(aggregate.replicate_ready ?? aggregate.ready_for_validation ?? false) ? "replicate-count ready" : "replicate-count"}>{(aggregate.replicate_ready ?? aggregate.ready_for_validation ?? false) ? "Replicate gate met" : "Not ready"}</span>
                </div>
                <div className="replicate-stat-grid">
                  <MetricCard label="Mean modulus" value={aggregate.mean_mpa === null ? "—" : formatNumber(aggregate.mean_mpa, 2)} unit="MPa" note={`${aggregate.n_valid} valid specimens`} icon={<Activity size={16} />} accent="teal" />
                  <MetricCard label="Sample standard deviation" value={aggregate.sample_standard_deviation_mpa === null ? "—" : formatNumber(aggregate.sample_standard_deviation_mpa, 2)} unit="MPa" note="Sample SD (n − 1)" icon={<BarChart3 size={16} />} accent="blue" />
                  <MetricCard label="Coefficient of variation" value={aggregate.coefficient_of_variation_percent === null ? "—" : formatNumber(aggregate.coefficient_of_variation_percent, 2)} unit="%" note={`Limit ${formatNumber(aggregate.maximum_cv_percent, 1)}%`} icon={<Gauge size={16} />} accent="amber" />
                </div>
                {aggregate.reason && <p className="campaign-reduction-reason">{aggregate.reason}</p>}
                <div className="table-scroll" role="region" aria-label={`${configuration.configuration_label} specimen modulus details`} tabIndex={0}>
                  <table><caption>One reduction per physical specimen</caption><thead><tr><th>Specimen</th><th>Status</th><th>Modulus (MPa)</th><th>Reason</th></tr></thead><tbody>
                    {configuration.specimen_reductions.map((specimen) => <tr key={specimen.specimen_id}><td>{specimen.specimen_id}</td><td>{specimen.status === "eligible" ? "Eligible" : "Needs review"}</td><td>{specimen.modulus_mpa === null ? "—" : formatNumber(specimen.modulus_mpa, 2)}</td><td>{specimen.reason ?? "—"}</td></tr>)}
                  </tbody></table>
                </div>
              </section>
            );
          })}
        </div>
      )}
    </section>
  );
}

function MetricCard(props: { label: string; value: string; unit: string; note: string; icon: ReactNode; accent: string }) {
  return <section className={`metric-card ${props.accent}`}><div className="metric-top"><span>{props.label}</span><span className="metric-icon">{props.icon}</span></div><div className="metric-value">{props.value}<small>{props.unit}</small></div><div className="metric-note">{props.note}</div></section>;
}
