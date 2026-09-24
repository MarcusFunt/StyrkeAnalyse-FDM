import { lazy, Suspense, useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
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
import { parseWorkspaceText, type StudyWorkspace } from "./lib/workspace";

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

interface AnalysisPoint {
  row_number: number;
  force_n: number;
  displacement_mm: number;
  extension_mm: number;
  strain: number;
  stress_mpa: number;
}

interface AnalysisResponse {
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

interface DesktopStudy {
  id: string;
  study_name: string;
  source_file_name: string;
  saved_at: string;
  analysis_time: string;
}

const initialSettings: Settings = {
  forceColumn: "",
  displacementColumn: "",
  forceUnit: "N",
  displacementUnit: "mm",
  decimalSeparator: ".",
  tensionDirection: "positive",
  widthMm: "10",
  thicknessMm: "2",
  gaugeLengthMm: "50",
};

function guessColumn(columns: string[], pattern: RegExp): string {
  return columns.find((column) => pattern.test(column)) ?? columns[0] ?? "";
}

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

export default function App() {
  const [page, setPage] = useState<Page>("overview");
  const [apiState, setApiState] = useState<ApiState>("checking");
  const [studyName, setStudyName] = useState("FDM tensile study");
  const [sourceFileName, setSourceFileName] = useState("");
  const [columns, setColumns] = useState<string[]>([]);
  const [rows, setRows] = useState<CsvRow[]>([]);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [settings, setSettings] = useState<Settings>(initialSettings);
  const [analysis, setAnalysis] = useState<AnalysisResponse | null>(null);
  const [analysisTime, setAnalysisTime] = useState("");
  const [serverStudyId, setServerStudyId] = useState("");
  const [serverStudies, setServerStudies] = useState<DesktopStudy[]>([]);
  const [showDesktopStudies, setShowDesktopStudies] = useState(false);
  const [isSavingDesktop, setIsSavingDesktop] = useState(false);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [message, setMessage] = useState("");
  const csvInput = useRef<HTMLInputElement>(null);
  const workspaceInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    fetch("/api/health")
      .then((response) => {
        if (!response.ok) throw new Error("API unavailable");
        return response.json();
      })
      .then(() => setApiState("ready"))
      .catch(() => setApiState("offline"));
  }, []);

  const canAnalyze =
    rows.length > 0 &&
    Boolean(settings.forceColumn) &&
    Boolean(settings.displacementColumn) &&
    Number(settings.widthMm) > 0 &&
    Number(settings.thicknessMm) > 0 &&
    Number(settings.gaugeLengthMm) > 0 &&
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
  }

  async function loadCsv(file: File): Promise<void> {
    setMessage("");
    if (file.size > 12 * 1024 * 1024) {
      setMessage("This file is larger than 12 MB. Split it into smaller test files and import one at a time.");
      return;
    }
    try {
      const parsed = parseCsvText(await file.text());
      setSourceFileName(file.name);
      setServerStudyId("");
      setColumns(parsed.columns);
      setRows(parsed.rows);
      setWarnings(parsed.warnings);
      setAnalysis(null);
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

  function applyWorkspace(workspace: StudyWorkspace): void {
    setStudyName(workspace.study_name);
    setServerStudyId(workspace.id ?? "");
    setSourceFileName(workspace.source_file_name);
    setColumns(workspace.columns);
    setRows(workspace.rows);
    setSettings({
      ...initialSettings,
      forceColumn: asString(workspace.settings.forceColumn, workspace.columns[0] ?? ""),
      displacementColumn: asString(workspace.settings.displacementColumn, workspace.columns[1] ?? ""),
      forceUnit: asUnit<ForceUnit>(workspace.settings.forceUnit, ["N", "kN"], "N"),
      displacementUnit: asUnit<DisplacementUnit>(workspace.settings.displacementUnit, ["mm", "cm"], "mm"),
      decimalSeparator: asUnit<"." | ",">(workspace.settings.decimalSeparator, [".", ","], "."),
      tensionDirection: asUnit<TensionDirection>(workspace.settings.tensionDirection, ["positive", "negative"], "positive"),
      widthMm: String(workspace.settings.widthMm ?? "10"),
      thicknessMm: String(workspace.settings.thicknessMm ?? "2"),
      gaugeLengthMm: String(workspace.settings.gaugeLengthMm ?? "50"),
    });
    setAnalysis(workspace.result as AnalysisResponse | null);
    setAnalysisTime(workspace.analysis_time || (workspace.result ? workspace.saved_at : ""));
    setWarnings([]);
    setPage("overview");
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
    return {
      format: "styrkeanalyse-fdm-study",
      version: 1,
      id: serverStudyId || undefined,
      saved_at: new Date().toISOString(),
      analysis_time: analysisTime,
      study_name: studyName.trim() || "FDM tensile study",
      source_file_name: sourceFileName,
      columns,
      rows,
      settings: {
        forceColumn: settings.forceColumn,
        displacementColumn: settings.displacementColumn,
        forceUnit: settings.forceUnit,
        displacementUnit: settings.displacementUnit,
        decimalSeparator: settings.decimalSeparator,
        tensionDirection: settings.tensionDirection,
        widthMm: settings.widthMm,
        thicknessMm: settings.thicknessMm,
        gaugeLengthMm: settings.gaugeLengthMm,
      },
      result: analysis,
    };
  }

  function saveWorkspace(): void {
    const workspace = createWorkspace();
    downloadFile(
      `${(studyName.trim() || "fdm-study").toLowerCase().replace(/[^a-z0-9]+/g, "-")}.fdmstudy.json`,
      JSON.stringify(workspace, null, 2),
      "application/json",
    );
  }

  async function refreshDesktopStudies(openPanel: boolean): Promise<void> {
    setMessage("");
    try {
      const response = await fetch("/api/studies");
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error ?? "Could not read studies saved on this desktop.");
      setServerStudies(payload.studies as DesktopStudy[]);
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
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(workspace),
      });
      if (response.status === 404 && serverStudyId) {
        response = await fetch("/api/studies", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(workspace),
        });
      }
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error ?? "Could not save this study to the desktop.");
      setServerStudyId(payload.id as string);
      await refreshDesktopStudies(showDesktopStudies);
      setMessage("Study saved on the desktop. It will be here when you reconnect.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not save this study to the desktop.");
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
    setMessage("");
    setIsAnalyzing(true);
    try {
      const response = await fetch("/api/analysis/tensile", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          rows,
          force_column: settings.forceColumn,
          displacement_column: settings.displacementColumn,
          width_mm: Number(settings.widthMm),
          thickness_mm: Number(settings.thicknessMm),
          gauge_length_mm: Number(settings.gaugeLengthMm),
          force_unit: settings.forceUnit,
          displacement_unit: settings.displacementUnit,
          decimal_separator: settings.decimalSeparator,
          tension_direction: settings.tensionDirection,
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error ?? "Analysis failed. Check the mapped columns and units.");
      setAnalysis(payload as AnalysisResponse);
      setAnalysisTime(new Date().toISOString());
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
          <button className={page === "overview" ? "nav-item active" : "nav-item"} onClick={() => setPage("overview")}>
            <Gauge size={17} /><span>Overview</span>
          </button>
          <button className={page === "data" ? "nav-item active" : "nav-item"} onClick={() => setPage("data")}>
            <Database size={17} /><span>Data & setup</span>{rows.length > 0 && <span className="nav-count">{rows.length}</span>}
          </button>
          <button className={page === "results" ? "nav-item active" : "nav-item"} onClick={() => setPage("results")}>
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
              <div className="desktop-study-popover" aria-label="Studies saved on the desktop">
                <div className="desktop-study-heading"><strong>Saved on this desktop</strong><button aria-label="Close saved studies" onClick={() => setShowDesktopStudies(false)}>×</button></div>
                {serverStudies.length === 0 ? <p>No studies saved here yet. Save the current study to keep it on the host.</p> : serverStudies.map((study) => (
                  <button className="desktop-study-row" key={study.id} onClick={() => void openDesktopStudy(study.id)}>
                    <span><strong>{study.study_name}</strong><small>{study.source_file_name || "No source file"}</small></span>
                    <small>{new Date(study.saved_at).toLocaleDateString()}</small>
                  </button>
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
              setSetting={setSetting}
              isDragging={isDragging}
              onFileDrop={(file) => void loadCsv(file)}
              onDragChange={setIsDragging}
              onChooseFile={() => csvInput.current?.click()}
              onTemplate={downloadTemplate}
              onAnalyze={runAnalysis}
              canAnalyze={canAnalyze}
              isAnalyzing={isAnalyzing}
              apiState={apiState}
            />
          )}

          {page === "results" && (
            <ResultsPage
              analysis={analysis}
              analysisTime={analysisTime}
              sourceFileName={sourceFileName}
              forceChart={forceChart}
              stressChart={stressChart}
              rowCount={rows.length}
              onData={() => setPage("data")}
              onAnalyze={() => setPage("data")}
              onDownloadCsv={downloadReducedCsv}
              onDownloadJson={downloadAnalysisJson}
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
  sourceFileName: string;
  columns: string[];
  rows: CsvRow[];
  warnings: string[];
  settings: Settings;
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

        {!isEmpty && (
          <>
            <section className="panel mapping-panel">
              <div className="panel-heading"><div><div className="section-eyebrow">02 · COLUMN MAPPING</div><h2>Tell us what each column means</h2><p>We suggest matches by header name. Check them before continuing.</p></div><div className="step-mini"><span>1</span><span>2</span><span>3</span></div></div>
              <div className="mapping-grid">
                <SelectField label="Force column" value={props.settings.forceColumn} options={props.columns} onChange={(value) => props.setSetting("forceColumn", value)} />
                <SelectField label="Displacement column" value={props.settings.displacementColumn} options={props.columns} onChange={(value) => props.setSetting("displacementColumn", value)} />
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
          <div className="readiness-list">
            <ReadinessItem done={!isEmpty} label="Test file imported" />
            <ReadinessItem done={Boolean(props.settings.forceColumn && props.settings.displacementColumn)} label="Columns mapped" />
            <ReadinessItem done={Number(props.settings.widthMm) > 0 && Number(props.settings.thicknessMm) > 0 && Number(props.settings.gaugeLengthMm) > 0} label="Dimensions entered" />
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
          {props.apiState === "offline" && <div className="offline-hint">Start the GUI service with <code>docker compose up gui</code>.</div>}
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

function SelectField(props: { label: string; value: string; options: string[]; onChange: (value: string) => void }) {
  return <label className="field"><span>{props.label}</span><select value={props.value} onChange={(event) => props.onChange(event.target.value)}>{props.options.map((option) => <option value={option} key={option}>{option}</option>)}</select></label>;
}

function NumberField(props: { label: string; unit: string; value: string; onChange: (value: string) => void }) {
  return <label className="field"><span>{props.label}</span><div className="number-input"><input type="number" min="0.000001" step="any" value={props.value} onChange={(event) => props.onChange(event.target.value)} /><span>{props.unit}</span></div></label>;
}

function ReadinessItem(props: { done: boolean; label: string }) {
  return <div className={props.done ? "readiness-item done" : "readiness-item"}><span>{props.done ? <Check size={11} /> : ""}</span><label>{props.label}</label></div>;
}

interface ResultsPageProps {
  analysis: AnalysisResponse | null;
  analysisTime: string;
  sourceFileName: string;
  forceChart: EChartsOption;
  stressChart: EChartsOption;
  rowCount: number;
  onData: () => void;
  onAnalyze: () => void;
  onDownloadCsv: () => void;
  onDownloadJson: () => void;
}

function ResultsPage(props: ResultsPageProps) {
  if (!props.analysis) {
    return <div className="empty-results"><div className="empty-results-icon"><BarChart3 size={24} /></div><h2>No results yet</h2><p>Import a tensile test, confirm its columns and specimen dimensions, then run the baseline analysis.</p><button className="button button-primary" onClick={props.onAnalyze}><Settings2 size={15} /> Go to data setup<ArrowRight size={14} /></button></div>;
  }
  const summary = props.analysis.summary;
  return (
    <>
      <section className="result-runbar">
        <div className="run-status-icon"><CheckCircle2 size={17} /></div>
        <div><strong>Tensile baseline complete</strong><span>{props.sourceFileName} · {summary.sample_count.toLocaleString()} measurements · {props.analysisTime ? new Date(props.analysisTime).toLocaleString() : ""}</span></div>
        <div className="runbar-actions"><button className="button button-secondary button-small" onClick={props.onDownloadJson}><ArrowDownToLine size={14} /> Analysis JSON</button><button className="button button-secondary button-small" onClick={props.onDownloadCsv}><ArrowDownToLine size={14} /> Reduced CSV</button><button className="icon-button" aria-label="Change analysis setup" onClick={props.onData}><Settings2 size={16} /></button></div>
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
            <ResultsChart option={props.forceChart} />
          </Suspense>
        </section>
        <section className="panel chart-panel">
          <div className="chart-heading"><div><div className="section-eyebrow">CALCULATED RESPONSE</div><h2>Nominal stress vs. strain</h2><p>Stress = force / area; strain = extension / gauge length.</p></div><span className="chart-unit-tag">MPa · %</span></div>
          <Suspense fallback={<div className="chart-loading">Loading chart…</div>}>
            <ResultsChart option={props.stressChart} />
          </Suspense>
        </section>
      </div>

      <section className="panel result-table-panel">
        <div className="panel-heading"><div><div className="section-eyebrow">REDUCED DATA</div><h2>Calculated values</h2><p>First {Math.min(20, props.analysis.points.length)} of {props.analysis.points.length.toLocaleString()} rows.</p></div><button className="text-button" onClick={props.onDownloadCsv}><ArrowDownToLine size={14} /> Export all rows</button></div>
        <div className="table-scroll"><table><thead><tr><th>Row</th><th>Force (N)</th><th>Displacement (mm)</th><th>Extension (mm)</th><th>Strain (mm/mm)</th><th>Stress (MPa)</th></tr></thead><tbody>{props.analysis.points.slice(0, 20).map((point) => <tr key={point.row_number}><td className="row-index">{point.row_number}</td><td>{formatNumber(point.force_n, 4)}</td><td>{formatNumber(point.displacement_mm, 4)}</td><td>{formatNumber(point.extension_mm, 4)}</td><td>{formatNumber(point.strain, 6)}</td><td className="stress-value">{formatNumber(point.stress_mpa, 4)}</td></tr>)}</tbody></table></div>
      </section>

      <div className="result-limit-note"><Info size={15} /><span>This is a nominal tensile baseline only. It does not include machine-compliance correction, replicate statistics, material calibration or FEM predictions.</span></div>
    </>
  );
}

function MetricCard(props: { label: string; value: string; unit: string; note: string; icon: ReactNode; accent: string }) {
  return <section className={`metric-card ${props.accent}`}><div className="metric-top"><span>{props.label}</span><span className="metric-icon">{props.icon}</span></div><div className="metric-value">{props.value}<small>{props.unit}</small></div><div className="metric-note">{props.note}</div></section>;
}
