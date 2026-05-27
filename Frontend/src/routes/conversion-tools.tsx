import { createFileRoute } from "@tanstack/react-router";
import React, { useState } from "react";
import { AppShell, PageHeader } from "@/components/app-shell";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Badge } from "@/components/ui/badge";
import { Slider } from "@/components/ui/slider";
import { cn } from "@/lib/utils";
import {
  MapPin, Scale, Layers3, ArrowRight, ArrowLeft,
  CheckCircle2, Loader2, AlertCircle, Bus, Cable, Zap, Users, Plug,
  CalendarDays, TrendingUp, Database, Activity, ChevronDown,
} from "lucide-react";
import { Link } from "@tanstack/react-router";
import {
  API_BASE,
  convertOpenDSS, simulateOpenDSS, saveOpenDSSNetwork,
  type ConvertOpenDSSResult, type SimulateOpenDSSResult, type SaveOpenDSSResult,
  type ValidationPhase, type ValidationBusEntry, type ValidationLoadingEntry,
} from "@/lib/api";
import { addConversionEvent } from "@/lib/conversions-store";
import { getCurrentUserInfo } from "@/lib/auth";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Cell,
} from "recharts";

export const Route = createFileRoute("/conversion-tools")({
  head: () => ({
    meta: [
      { title: "Conversion Tools — DT Lab" },
      { name: "description", content: "Convert and import network models from external simulation tools." },
    ],
  }),
  component: ConversionToolsPage,
});

// ── Tool catalogue ──────────────────────────────────────────────────────────

const TOOLS = [
  {
    id: "opendss",
    name: "OpenDSS",
    tagline: "Convert OpenDSS distribution network models to pandapower",
    available: true,
  },
  {
    id: "GridLab-D",
    name: "GridLab-D",
    tagline: "Import GridLab-D models as pandapower networks",
    available: false,
  },
  {
    id: "Power Grid Model",
    name: "PowerGridModel",
    tagline: "Import PowerGridModel networks and convert them to pandapower",
    available: false,
  },
] as const;

type ToolId = (typeof TOOLS)[number]["id"];

// ── OpenDSS network catalogue ───────────────────────────────────────────────

const NETWORKS = [
  { id: "1" as const, name: "Rural SMR8",   location: "Nagambie, VIC",        type: "Rural" as const, voltage: "66 kV / 22 kV / 0.4 kV", topology: "SWER + 3-phase LV" },
  { id: "2" as const, name: "Rural KLO14",  location: "Kilmore, VIC",          type: "Rural" as const, voltage: "66 kV / 22 kV / 0.4 kV", topology: "SWER + 3-phase LV" },
  { id: "3" as const, name: "Urban HPK11",  location: "Hoppers Crossing, VIC", type: "Urban" as const, voltage: "66 kV / 22 kV / 0.4 kV", topology: "3-phase MV + LV" },
  { id: "4" as const, name: "Urban CRE21",  location: "Cremorne, VIC",         type: "Urban" as const, voltage: "66 kV / 22 kV / 0.4 kV", topology: "3-phase MV + LV" },
];

type NetworkId = "1" | "2" | "3" | "4";

const SIM_MODES = [
  { id: "balanced"   as const, label: "Balanced",   description: "Single-phase equivalent load flow — faster, assumes symmetric loading across phases." },
  { id: "unbalanced" as const, label: "Unbalanced", description: "Full 3-phase simulation — per-phase detail, required for SWER and split-phase networks." },
];

const STEPS = ["Select Network & Mode", "Validate & Simulate"];

// ── Utilities ───────────────────────────────────────────────────────────────

function dayToLabel(day: number): string {
  // use a non-leap year base; day 1 = Jan 1
  const d = new Date(2023, 0, day);
  return d.toLocaleDateString("en-AU", { month: "long", day: "numeric" });
}

function dayToSeason(day: number): string {
  // Southern hemisphere
  if (day >= 355 || day <= 78)  return "Summer";
  if (day <= 170)               return "Autumn";
  if (day <= 263)               return "Winter";
  return "Spring";
}

function mapeColor(pct: number): string {
  if (pct < 1)  return "text-green-600";
  if (pct < 3)  return "text-amber-500";
  return "text-red-500";
}

// ── Sub-components ──────────────────────────────────────────────────────────

function StepIndicator({ current }: { current: number }) {
  return (
    <div className="flex items-center gap-0 mb-8">
      {STEPS.map((label, i) => {
        const step = i + 1;
        const isActive = step === current;
        const isDone = step < current;
        return (
          <div key={step} className="flex items-center">
            <div className="flex items-center gap-2">
              <div className={cn(
                "w-7 h-7 rounded-full flex items-center justify-center text-xs font-semibold border-2 shrink-0",
                (isActive || isDone) && "border-primary bg-primary text-primary-foreground",
                !isActive && !isDone && "border-border text-muted-foreground bg-background",
              )}>
                {isDone ? <CheckCircle2 className="h-4 w-4" /> : step}
              </div>
              <span className={cn("text-sm font-medium whitespace-nowrap", isActive ? "text-foreground" : "text-muted-foreground")}>
                {label}
              </span>
            </div>
            {i < STEPS.length - 1 && (
              <div className={cn("h-px w-10 mx-3 shrink-0", isDone ? "bg-primary" : "bg-border")} />
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── Tool landing ────────────────────────────────────────────────────────────

function ToolLanding({ onSelect }: { onSelect: (tool: ToolId) => void }) {
  return (
    <>
      <PageHeader
        title="Conversion Tools"
        description="Select a conversion source to import network models into your workspace."
      />
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {TOOLS.map((tool) => (
          <button
            key={tool.id}
            disabled={!tool.available}
            onClick={() => tool.available && onSelect(tool.id)}
            className={cn(
              "text-left rounded-xl border p-6 transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              tool.available
                ? "border-border bg-card hover:border-primary/50 hover:bg-muted/30 hover:shadow-sm cursor-pointer"
                : "border-border bg-muted/20 opacity-50 cursor-not-allowed",
            )}
          >
            <div className="flex items-start justify-between mb-4">
              <div className="text-lg font-semibold">{tool.name}</div>
              {!tool.available && <Badge variant="secondary" className="text-[10px] shrink-0 ml-2">Coming soon</Badge>}
            </div>
            <p className="text-sm text-muted-foreground leading-relaxed">{tool.tagline}</p>
            {tool.available && (
              <div className="flex items-center gap-1 text-primary text-sm font-medium mt-4">
                Open <ArrowRight className="h-4 w-4" />
              </div>
            )}
          </button>
        ))}
      </div>
    </>
  );
}

// ── Step 1 result card ──────────────────────────────────────────────────────

type QuickSaveState =
  | { phase: "idle" }
  | { phase: "saving" }
  | { phase: "saved"; networkId: string }
  | { phase: "error"; message: string };

function ConversionResult({
  result, onContinue, onReset,
}: {
  result: ConvertOpenDSSResult;
  onContinue: () => void;
  onReset: () => void;
}) {
  const [saveState, setSaveState] = useState<QuickSaveState>({ phase: "idle" });

  const stats = [
    { label: "Buses",        value: result.network_stats.buses,        icon: Bus },
    { label: "Lines",        value: result.network_stats.lines,        icon: Cable },
    { label: "Transformers", value: result.network_stats.transformers, icon: Zap },
    { label: "Loads",        value: result.network_stats.loads,        icon: Plug },
    
  ];

  async function handleQuickSave() {
    setSaveState({ phase: "saving" });
    try {
      const r = await saveOpenDSSNetwork(result.network as NetworkId, result.mode);
      setSaveState({ phase: "saved", networkId: r.network_id });
      // Track as a "conversion" event (no simulation/validation was run).
      const d = new Date();
      const pad = (n: number) => String(n).padStart(2, "0");
      const now = `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
      addConversionEvent({
        networkId: r.network_id,
        networkName: String((r.network as Record<string, unknown>)["name"] ?? r.network_id),
        convertedAt: now,
        convertedBy: getCurrentUserInfo()?.name ?? "—",
        type: "conversion",
      });
    } catch (err) {
      setSaveState({ phase: "error", message: err instanceof Error ? err.message : String(err) });
    }
  }

  // ── Saved success screen ──
  if (saveState.phase === "saved") {
    return (
      <div className="space-y-4">
        <div className="flex items-center gap-3 p-4 rounded-xl border border-green-500/30 bg-green-500/5">
          <CheckCircle2 className="h-5 w-5 text-green-500 shrink-0" />
          <div>
            <div className="font-semibold text-sm">Network saved to workspace</div>
            <div className="text-xs text-muted-foreground font-mono">{saveState.networkId}</div>
          </div>
        </div>
        <div className="flex items-center justify-between border-t pt-5">
          <Button variant="ghost" size="sm" onClick={onReset} className="text-muted-foreground">
            Convert another
          </Button>
          <div className="flex gap-2">
            <Button variant="outline" onClick={onContinue} className="gap-2">
              Run Validation <ArrowRight className="h-4 w-4" />
            </Button>
            <Button asChild className="gap-2">
              <Link to="/networks">
                View in Networks <ArrowRight className="h-4 w-4" />
              </Link>
            </Button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 p-4 rounded-xl border border-green-500/30 bg-green-500/5">
        <CheckCircle2 className="h-5 w-5 text-green-500 shrink-0" />
        <div>
          <div className="font-semibold text-sm">
            {result.cached ? "Already converted — loaded from cache" : "Conversion complete"}
          </div>
          <div className="text-xs text-muted-foreground">
            {result.cached
              ? `${result.network_name} network files found, skipped pipeline`
              : `${result.network_name} converted in ${result.duration_seconds}s`}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[1fr_auto] gap-4 items-stretch">
        {/* Left — topology plot */}
        {result.plot_url ? (
          <Card className="p-0 overflow-hidden">
            <div className="px-5 pt-4 pb-3 text-sm font-semibold shrink-0">Topology overview</div>
            <div className="relative w-full h-[600px]">
              <iframe
                src={`${API_BASE}${result.plot_url}?v=${Date.now()}`}
                title={`${result.network_name} topology`}
                className="w-full h-full border-0 block"
              />
            </div>
          </Card>
        ) : (
          <Card className="p-5 flex items-center justify-center text-muted-foreground text-sm border-dashed" style={{ minHeight: 200 }}>
            No topology plot available
          </Card>
        )}

        {/* Right — asset counts (vertical, fills topology height) */}
        <div className="flex flex-col gap-3 xl:w-75">
          {stats.map(({ label, value, icon: Icon }) => (
            <Card key={label} className="p-4 flex-1 flex flex-col justify-center">
              <div className="flex items-center gap-2 text-muted-foreground mb-2">
                <Icon className="h-3.5 w-3.5" />
                <span className="text-xs uppercase tracking-wider font-medium">{label}</span>
              </div>
              <div className="text-2xl font-semibold">{value ?? "—"}</div>
            </Card>
          ))}
        </div>
      </div>

      {/* Save error */}
      {saveState.phase === "error" && (
        <div className="flex items-start gap-3 p-4 rounded-xl border border-destructive/30 bg-destructive/5">
          <AlertCircle className="h-4 w-4 text-destructive mt-0.5 shrink-0" />
          <div>
            <div className="text-sm font-medium text-destructive">Save failed</div>
            <div className="text-xs text-muted-foreground mt-1 font-mono whitespace-pre-wrap break-all">{saveState.message}</div>
          </div>
        </div>
      )}

      <div className="flex items-center justify-between border-t pt-5">
        <Button variant="ghost" size="sm" onClick={onReset} className="text-muted-foreground">
          Convert another
        </Button>
        <div className="flex gap-2">
          <Button
            variant="outline"
            disabled={saveState.phase === "saving"}
            onClick={handleQuickSave}
            className="gap-2"
          >
            {saveState.phase === "saving" ? (
              <><Loader2 className="h-4 w-4 animate-spin" />Saving…</>
            ) : (
              <><Database className="h-4 w-4" />Save to Workspace</>
            )}
          </Button>
          <Button onClick={onContinue} className="gap-2">
            Continue to Simulation <ArrowRight className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </div>
  );
}

// ── Daily validation output ─────────────────────────────────────────────────

function fmt(v: number | null | undefined, decimals = 3): string {
  if (v == null || Number.isNaN(v)) return "—";
  return v.toFixed(decimals);
}

function ValidationMetricCard({
  label, value, unit = "%", colored = false,
  icon: Icon = TrendingUp,
}: {
  label: string;
  value: number | null | undefined;
  unit?: string;
  colored?: boolean;
  icon?: React.ComponentType<{ className?: string }>;
}) {
  return (
    <Card className="p-4">
      <div className="flex items-center gap-2 text-muted-foreground mb-2">
        <Icon className="h-3.5 w-3.5" />
        <span className="text-xs uppercase tracking-wider font-medium">{label}</span>
      </div>
      <div className={cn(
        "text-2xl font-semibold tabular-nums",
        colored && value != null ? mapeColor(value) : "",
      )}>
        {value != null ? `${fmt(value)}${unit}` : "—"}
      </div>
    </Card>
  );
}

function PhaseTable({
  byPhase, isLoading = false,
}: {
  byPhase: Record<string, ValidationPhase>;
  isLoading?: boolean;
}) {
  const phases = Object.entries(byPhase).sort(([a], [b]) => a.localeCompare(b));
  if (!phases.length) return null;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-muted-foreground border-b border-border">
            <th className="text-left pb-2 pr-4 font-medium">Phase</th>
            <th className="text-right pb-2 px-3 font-medium">Matched</th>
            {isLoading ? (
              <>
                <th className="text-right pb-2 px-3 font-medium">MAE %</th>
                <th className="text-right pb-2 px-3 font-medium">Max AE %</th>
                <th className="text-right pb-2 px-3 font-medium">MBE %</th>
              </>
            ) : (
              <>
                <th className="text-right pb-2 px-3 font-medium">MAPE %</th>
                <th className="text-right pb-2 px-3 font-medium">Max %</th>
                <th className="text-right pb-2 px-3 font-medium">Bias %</th>
              </>
            )}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {phases.map(([ph, s]) => (
            <tr key={ph} className="tabular-nums">
              <td className="py-1.5 pr-4 font-medium">Phase {ph}</td>
              <td className="py-1.5 px-3 text-right">{s.matched}</td>
              {isLoading ? (
                <>
                  <td className="py-1.5 px-3 text-right">{fmt(s.mae)}</td>
                  <td className="py-1.5 px-3 text-right">{fmt(s.max_ae)}</td>
                  <td className="py-1.5 px-3 text-right">{fmt(s.mbe)}</td>
                </>
              ) : (
                <>
                  <td className={cn("py-1.5 px-3 text-right", s.mape != null ? mapeColor(s.mape) : "")}>
                    {fmt(s.mape)}
                  </td>
                  <td className="py-1.5 px-3 text-right">{fmt(s.max)}</td>
                  <td className="py-1.5 px-3 text-right">{fmt(s.bias)}</td>
                </>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function WorstBusTable({ items }: { items: ValidationBusEntry[] }) {
  if (!items.length) return null;
  return (
    <details className="group">
      <summary className="flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground cursor-pointer select-none list-none">
        <ChevronDown className="h-3 w-3 transition-transform group-open:rotate-180 shrink-0" />
        Top {items.length} worst buses
      </summary>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-muted-foreground border-b border-border">
              <th className="text-left pb-2 pr-4 font-medium">Bus</th>
              {items[0]?.phase !== undefined && <th className="text-left pb-2 px-3 font-medium">Ph</th>}
              <th className="text-right pb-2 px-3 font-medium">MAPE %</th>
              <th className="text-right pb-2 px-3 font-medium">Max %</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {items.map((item, i) => (
              <tr key={i} className="tabular-nums">
                <td className="py-1 pr-4 font-mono text-[11px] max-w-[240px] truncate">{item.bus_name}</td>
                {item.phase !== undefined && <td className="py-1 px-3">{item.phase}</td>}
                <td className={cn("py-1 px-3 text-right", item.mape != null ? mapeColor(item.mape) : "")}>
                  {fmt(item.mape)}
                </td>
                <td className="py-1 px-3 text-right">{fmt(item.max)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

function WorstElementTable({ items, label }: { items: ValidationLoadingEntry[]; label: string }) {
  if (!items.length) return null;
  return (
    <details className="group">
      <summary className="flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground cursor-pointer select-none list-none">
        <ChevronDown className="h-3 w-3 transition-transform group-open:rotate-180 shrink-0" />
        Top {items.length} worst {label}
      </summary>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-muted-foreground border-b border-border">
              <th className="text-left pb-2 pr-4 font-medium">Element</th>
              <th className="text-left pb-2 px-3 font-medium">Ph</th>
              <th className="text-right pb-2 px-3 font-medium">MAE %</th>
              <th className="text-right pb-2 px-3 font-medium">Max AE %</th>
              <th className="text-right pb-2 px-3 font-medium">MBE %</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {items.map((item, i) => (
              <tr key={i} className="tabular-nums">
                <td className="py-1 pr-4 font-mono text-[11px] max-w-[240px] truncate">{item.dss_name}</td>
                <td className="py-1 px-3">{item.phase}</td>
                <td className="py-1 px-3 text-right">{fmt(item.mae)}</td>
                <td className="py-1 px-3 text-right">{fmt(item.max_ae)}</td>
                <td className="py-1 px-3 text-right">{fmt(item.mbe)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

function ValidationSection({
  icon: Icon, iconClass = "text-primary", title, subtitle, children,
}: {
  icon: React.ComponentType<{ className?: string }>;
  iconClass?: string;
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="flex items-center gap-2 mb-3">
        <Icon className={cn("h-3.5 w-3.5 shrink-0", iconClass)} />
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{title}</h3>
        {subtitle && <span className="text-xs text-muted-foreground">— {subtitle}</span>}
      </div>
      {children}
    </div>
  );
}

// ── Validation overview bar chart ───────────────────────────────────────────

const CHART_COLORS = [
  "oklch(0.58 0.22 25)",   // red   — bus voltage
  "oklch(0.65 0.14 230)",  // blue  — MV lines
  "oklch(0.75 0.16 75)",   // amber — LV lines
  "oklch(0.55 0.18 290)",  // purple — transformers
];

function ValidationOverviewChart({ result }: { result: SimulateOpenDSSResult }) {
  const { validation } = result;
  if (!validation) return null;

  const { bus_voltage, mv_line_loading, lv_line_loading, trafo_loading } = validation;

  const rows = [
    { label: "Bus Voltage",  value: bus_voltage.mape,      metric: "MAPE" },
    { label: "MV Lines",     value: mv_line_loading?.mae,  metric: "MAE"  },
    { label: "LV Lines",     value: lv_line_loading?.mae,  metric: "MAE"  },
    { label: "Transformers", value: trafo_loading?.mae,     metric: "MAE"  },
  ].filter((r): r is { label: string; value: number; metric: string } =>
    r.value != null && Number.isFinite(r.value),
  );

  if (rows.length === 0) return null;

  const tooltipStyle = {
    backgroundColor: "var(--card)",
    border: "1px solid var(--border)",
    borderRadius: 6,
    fontSize: 12,
  };

  return (
    <Card className="p-5">
      <div className="mb-4">
        <div className="text-sm font-semibold mb-1">Validation Overview</div>
        <div className="text-xs text-muted-foreground">
          MAPE for bus voltage · MAE for line and transformer loadings (%)
        </div>
      </div>
      <div className="h-56">
        <ResponsiveContainer>
          <BarChart data={rows} margin={{ top: 5, right: 16, left: -10, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="oklch(0.91 0.01 240)" />
            <XAxis dataKey="label" stroke="oklch(0.5 0.02 250)" fontSize={11} />
            <YAxis stroke="oklch(0.5 0.02 250)" fontSize={11} unit="%" tickCount={6} />
            <Tooltip
              contentStyle={tooltipStyle}
              formatter={(value, _name, entry) => [
                `${(value as number).toFixed(3)} %`,
                (entry.payload as { metric: string }).metric,
              ]}
            />
            <Bar dataKey="value" radius={[4, 4, 0, 0]} maxBarSize={80}>
              {rows.map((_, i) => (
                <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}

function DailyValidationOutput({ result }: { result: SimulateOpenDSSResult }) {
  const { validation, mode, day, duration_seconds, validation_start, validation_end, n_timesteps, validation_hours } = result;
  if (!validation) return null;

  const { bus_voltage, mv_line_loading, lv_line_loading, trafo_loading } = validation;
  const isUnbalanced = mode === "unbalanced";
  const hasPhaseData = Object.keys(bus_voltage.by_phase).length > 0;

  const windowLabel = validation_start && validation_end
    ? `${validation_start} – ${validation_end}`
    : null;
  const stepsLabel = n_timesteps != null ? `${n_timesteps} steps × 30 min` : null;
  const hoursLabel = validation_hours != null
    ? validation_hours === 24 ? "Full day" : `${validation_hours}h window`
    : null;

  return (
    <div className="space-y-8">
      {/* Run context header */}
      <div>
        <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
          Validation Results — {dayToLabel(day)} (Day {day})
        </h2>
        <p className="text-xs text-muted-foreground mt-0.5">
          pandapower vs OpenDSS · {mode} · {duration_seconds}s
          {windowLabel && (
            <> · <span className="font-medium text-foreground">Validation window: {windowLabel}</span>{hoursLabel && <> ({hoursLabel})</>}{stepsLabel && <>, {stepsLabel}</>}</>
          )}
        </p>
      </div>

      {/* ── Overview bar chart ── */}
      <ValidationOverviewChart result={result} />

      {/* ── Bus Voltage ── */}
      <ValidationSection
        icon={Activity}
        title="Bus Voltage"
        subtitle={
          bus_voltage.matched != null
            ? `${bus_voltage.matched} ${isUnbalanced ? "(bus, phase) pairs" : "buses"} · ${bus_voltage.total_points ?? "?"} comparison points`
            : undefined
        }
      >
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <ValidationMetricCard label="Global MAPE" value={bus_voltage.mape}      colored />
          <ValidationMetricCard label="Max Error"   value={bus_voltage.max_error} />
          <ValidationMetricCard label="Global Bias" value={bus_voltage.bias}      />
        </div>
        {hasPhaseData && (
          <Card className="p-4 mt-3 space-y-1">
            <p className="text-xs font-medium text-muted-foreground mb-2">Per-phase breakdown</p>
            <PhaseTable byPhase={bus_voltage.by_phase} />
          </Card>
        )}
        {bus_voltage.worst_buses.length > 0 && (
          <Card className="p-4 mt-3">
            <WorstBusTable items={bus_voltage.worst_buses} />
          </Card>
        )}
      </ValidationSection>

      {/* ── MV Line Loading ── */}
      {mv_line_loading && (
        <ValidationSection
          icon={Cable}
          title="MV Line Loading"
          subtitle={`${mv_line_loading.matched_elements} elements matched`}
        >
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <ValidationMetricCard label="MAE"    value={mv_line_loading.mae}    />
            <ValidationMetricCard label="Max AE" value={mv_line_loading.max_ae} />
            <ValidationMetricCard label="MBE"    value={mv_line_loading.mbe}    />
          </div>
          {Object.keys(mv_line_loading.by_phase).length > 0 && (
            <Card className="p-4 mt-3 space-y-1">
              <p className="text-xs font-medium text-muted-foreground mb-2">Per-phase breakdown</p>
              <PhaseTable byPhase={mv_line_loading.by_phase} isLoading />
            </Card>
          )}
          {mv_line_loading.worst.length > 0 && (
            <Card className="p-4 mt-3">
              <WorstElementTable items={mv_line_loading.worst} label="MV lines" />
            </Card>
          )}
        </ValidationSection>
      )}

      {/* ── LV Line Loading ── */}
      {lv_line_loading && (
        <ValidationSection
          icon={Cable}
          title="LV Line Loading"
          subtitle={`${lv_line_loading.matched_elements} elements matched`}
        >
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <ValidationMetricCard label="MAE"    value={lv_line_loading.mae}    />
            <ValidationMetricCard label="Max AE" value={lv_line_loading.max_ae} />
            <ValidationMetricCard label="MBE"    value={lv_line_loading.mbe}    />
          </div>
          {Object.keys(lv_line_loading.by_phase).length > 0 && (
            <Card className="p-4 mt-3 space-y-1">
              <p className="text-xs font-medium text-muted-foreground mb-2">Per-phase breakdown</p>
              <PhaseTable byPhase={lv_line_loading.by_phase} isLoading />
            </Card>
          )}
          {lv_line_loading.worst.length > 0 && (
            <Card className="p-4 mt-3">
              <WorstElementTable items={lv_line_loading.worst} label="LV lines" />
            </Card>
          )}
        </ValidationSection>
      )}

      {/* ── Transformer Loading (unbalanced only) ── */}
      {trafo_loading && (
        <ValidationSection
          icon={Zap}
          iconClass="text-warning-foreground"
          title="Transformer Loading"
          subtitle={`${trafo_loading.matched_elements} elements matched`}
        >
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <ValidationMetricCard label="MAE"    value={trafo_loading.mae}    />
            <ValidationMetricCard label="Max AE" value={trafo_loading.max_ae} />
            <ValidationMetricCard label="MBE"    value={trafo_loading.mbe}    />
          </div>
          {Object.keys(trafo_loading.by_phase).length > 0 && (
            <Card className="p-4 mt-3 space-y-1">
              <p className="text-xs font-medium text-muted-foreground mb-2">Per-phase breakdown</p>
              <PhaseTable byPhase={trafo_loading.by_phase} isLoading />
            </Card>
          )}
          {trafo_loading.worst.length > 0 && (
            <Card className="p-4 mt-3">
              <WorstElementTable items={trafo_loading.worst} label="transformers" />
            </Card>
          )}
        </ValidationSection>
      )}
    </div>
  );
}

// ── Step 2: day picker + simulation ────────────────────────────────────────

type SimState =
  | { phase: "idle" }
  | { phase: "simulating" }
  | { phase: "done"; result: SimulateOpenDSSResult }
  | { phase: "error"; message: string };

type SaveState =
  | { phase: "idle" }
  | { phase: "saving" }
  | { phase: "saved"; result: SaveOpenDSSResult }
  | { phase: "error"; message: string };

function SimulationStep({
  conversionResult,
  onStepDone,
}: {
  conversionResult: ConvertOpenDSSResult;
  onStepDone: () => void;
}) {
  const [day, setDay] = useState(15);
  const [validationHours, setValidationHours] = useState<1 | 2 | 4 | 24>(2);
  const [simState, setSimState] = useState<SimState>({ phase: "idle" });
  const [saveState, setSaveState] = useState<SaveState>({ phase: "idle" });

  async function handleSimulate() {
    setSimState({ phase: "simulating" });
    setSaveState({ phase: "idle" });
    try {
      const result = await simulateOpenDSS(
        conversionResult.network as NetworkId,
        conversionResult.mode,
        day,
        validationHours,
      );
      setSimState({ phase: "done", result });
    } catch (err) {
      setSimState({ phase: "error", message: err instanceof Error ? err.message : String(err) });
    }
  }

  async function handleSave() {
    if (simState.phase !== "done") return;
    setSaveState({ phase: "saving" });
    try {
      const result = await saveOpenDSSNetwork(
        conversionResult.network as NetworkId,
        conversionResult.mode,
        day,
        simState.result.metrics as Record<string, number | string>,
      );
      setSaveState({ phase: "saved", result });
      onStepDone();
      // Record the conversion event so it appears in the dashboard activity feed.
      const d = new Date();
      const pad = (n: number) => String(n).padStart(2, "0");
      const now = `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
      addConversionEvent({
        networkId: result.network_id,
        networkName: String((result.network as Record<string, unknown>)["name"] ?? result.network_id),
        convertedAt: now,
        convertedBy: getCurrentUserInfo()?.name ?? "—",
        type: "validation",
      });
    } catch (err) {
      setSaveState({ phase: "error", message: err instanceof Error ? err.message : String(err) });
    }
  }

  const isRunning = simState.phase === "simulating";
  const isSaving  = saveState.phase === "saving";
  const dateLabel = dayToLabel(day);
  const season    = dayToSeason(day);

  // ── Saved success screen ──
  if (saveState.phase === "saved") {
    const networkId = saveState.result.network_id;
    return (
      <div className="space-y-4">
        <div className="flex items-center gap-3 p-4 rounded-xl border border-green-500/30 bg-green-500/5">
          <CheckCircle2 className="h-5 w-5 text-green-500 shrink-0" />
          <div>
            <div className="font-semibold text-sm">Network saved to workspace</div>
            <div className="text-xs text-muted-foreground font-mono">{networkId}</div>
          </div>
        </div>
        <Card className="p-4">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
            {[
              ["Network", conversionResult.network_name],
              ["Mode", conversionResult.mode],
              ["Validated on", dateLabel],
              ["Status", "Validated"],
            ].map(([label, value]) => (
              <div key={label}>
                <div className="text-xs text-muted-foreground mb-0.5">{label}</div>
                <div className="font-medium capitalize">{value}</div>
              </div>
            ))}
          </div>
        </Card>
        <div className="flex items-center justify-between border-t pt-5">
          <Button variant="ghost" size="sm" onClick={() => { setSaveState({ phase: "idle" }); setSimState({ phase: "idle" }); }} className="text-muted-foreground">
            Convert another
          </Button>
          <Button asChild className="gap-2">
            <Link to="/networks">
              View in Networks <ArrowRight className="h-4 w-4" />
            </Link>
          </Button>
        </div>
      </div>
    );
  }

  return (
    <>
      {/* Day selection */}
      <div className="mb-6">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground mb-3">
          1 — Select Day of Year
        </h2>
        <Card className="p-6">
          <div className="flex items-center justify-between mb-6">
            <div className="flex items-center gap-2">
              <CalendarDays className="h-4 w-4 text-muted-foreground" />
              <span className="text-2xl font-semibold">{dateLabel}</span>
              <Badge variant="secondary" className="ml-1">{season}</Badge>
            </div>
            <span className="text-sm text-muted-foreground tabular-nums">Day {day} / 365</span>
          </div>
          <Slider
            min={1} max={365} step={1}
            value={[day]}
            onValueChange={([v]) => setDay(v)}
            disabled={isRunning || isSaving}
            className="w-full"
          />
          <div className="flex justify-between mt-2 text-xs text-muted-foreground">
            <span>Jan 1</span><span>Apr 1</span><span>Jul 2</span><span>Oct 1</span><span>Dec 31</span>
          </div>
        </Card>
      </div>

      {/* Validation window selector */}
      <div className="mb-8">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground mb-3">
          2 — Validation Window
        </h2>
        <Card className="p-4">
          <p className="text-xs text-muted-foreground mb-3">
            How many timesteps to simulate for the pandapower vs OpenDSS comparison.
            Shorter windows run faster; use <span className="font-medium text-foreground">Full day</span> for thorough validation studies.
          </p>
          <div className="grid grid-cols-4 gap-2">
            {([1, 2, 4, 24] as const).map((h) => {
              const label = h === 24 ? "Full day" : `${h}h`;
              const sub   = h === 24 ? "48 steps" : `${h * 2} steps`;
              const isSelected = validationHours === h;
              return (
                <button
                  key={h}
                  type="button"
                  disabled={isRunning}
                  onClick={() => setValidationHours(h)}
                  className={cn(
                    "rounded-lg border p-3 text-center transition-colors text-sm",
                    isSelected
                      ? "border-primary bg-primary/10 text-primary font-semibold"
                      : "border-border hover:border-primary/50 hover:bg-muted/50",
                    isRunning && "opacity-50 cursor-not-allowed",
                  )}
                >
                  <div className="font-medium">{label}</div>
                  <div className="text-[11px] text-muted-foreground mt-0.5">{sub} × 30 min</div>
                  {h === 2 && <div className="text-[10px] text-primary/80 mt-0.5">default</div>}
                </button>
              );
            })}
          </div>
        </Card>
      </div>

      {/* Simulation summary */}
      <div className="mb-8">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground mb-3">
          3 — Simulation Summary
        </h2>
        <Card className="p-4">
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 text-sm">
            <div><div className="text-xs text-muted-foreground mb-0.5">Network</div><div className="font-medium">{conversionResult.network_name}</div></div>
            <div><div className="text-xs text-muted-foreground mb-0.5">Mode</div><div className="font-medium capitalize">{conversionResult.mode}</div></div>
            <div>
              <div className="text-xs text-muted-foreground mb-0.5">Validation window</div>
              <div className="font-medium">
                {validationHours === 24 ? "Full day (48 steps)" : `${validationHours}h (${validationHours * 2} steps × 30 min)`}
              </div>
            </div>
          </div>
        </Card>
      </div>

      {/* Validation output — updates whenever a new run completes */}
      {simState.phase === "done" && (
        <div className="mb-8">
          <DailyValidationOutput result={simState.result} />
        </div>
      )}

      {/* Error banners */}
      {simState.phase === "error" && (
        <div className="flex items-start gap-3 p-4 rounded-xl border border-destructive/30 bg-destructive/5 mb-6">
          <AlertCircle className="h-4 w-4 text-destructive mt-0.5 shrink-0" />
          <div>
            <div className="text-sm font-medium text-destructive">Simulation failed</div>
            <div className="text-xs text-muted-foreground mt-1 font-mono whitespace-pre-wrap break-all">{simState.message}</div>
          </div>
        </div>
      )}
      {saveState.phase === "error" && (
        <div className="flex items-start gap-3 p-4 rounded-xl border border-destructive/30 bg-destructive/5 mb-6">
          <AlertCircle className="h-4 w-4 text-destructive mt-0.5 shrink-0" />
          <div>
            <div className="text-sm font-medium text-destructive">Save failed</div>
            <div className="text-xs text-muted-foreground mt-1 font-mono whitespace-pre-wrap break-all">{saveState.message}</div>
          </div>
        </div>
      )}

      {/* Actions */}
      <div className="flex items-center justify-between border-t pt-5">
        <div className="text-sm text-muted-foreground">
          {isRunning ? (
            <span className="flex items-center gap-2"><Loader2 className="h-3.5 w-3.5 animate-spin" />Running simulations — this may take several minutes…</span>
          ) : isSaving ? (
            <span className="flex items-center gap-2"><Loader2 className="h-3.5 w-3.5 animate-spin" />Saving to workspace…</span>
          ) : simState.phase === "done" ? (
            "Simulation complete. Save the network to make it available for future runs."
          ) : (
            <>Simulate <span className="font-medium text-foreground">{dateLabel}</span> for {conversionResult.network_name}</>
          )}
        </div>
        <div className="flex gap-2">
          {simState.phase === "done" && (
            <Button variant="outline" disabled={isSaving} onClick={() => { setSimState({ phase: "idle" }); setSaveState({ phase: "idle" }); }}>
              Re-run
            </Button>
          )}
          {simState.phase !== "done" ? (
            <Button disabled={isRunning} onClick={handleSimulate} className="gap-2">
              {isRunning ? <><Loader2 className="h-4 w-4 animate-spin" />Simulating…</> : <>Run Simulation <ArrowRight className="h-4 w-4" /></>}
            </Button>
          ) : (
            <Button disabled={isSaving} onClick={handleSave} className="gap-2">
              {isSaving ? <><Loader2 className="h-4 w-4 animate-spin" />Saving…</> : <><Database className="h-4 w-4" />Save to Workspace</>}
            </Button>
          )}
        </div>
      </div>
    </>
  );
}

// ── OpenDSS full flow ───────────────────────────────────────────────────────

type ConvState =
  | { phase: "idle" }
  | { phase: "converting" }
  | { phase: "done"; result: ConvertOpenDSSResult }
  | { phase: "error"; message: string };

function OpenDSSFlow({ onBack }: { onBack: () => void }) {
  const [step, setStep] = useState<1 | 2>(1);
  const [selectedNetwork, setSelectedNetwork] = useState<NetworkId | null>(null);
  const [simMode, setSimMode] = useState<"balanced" | "unbalanced">("balanced");
  const [convState, setConvState] = useState<ConvState>({ phase: "idle" });

  const selectedNet = NETWORKS.find((n) => n.id === selectedNetwork);
  const canConvert = selectedNetwork !== null && convState.phase === "idle";
  const isConverting = convState.phase === "converting";

  async function handleConvert() {
    if (!selectedNetwork) return;
    setConvState({ phase: "converting" });
    try {
      const result = await convertOpenDSS(selectedNetwork, simMode);
      setConvState({ phase: "done", result });
    } catch (err) {
      setConvState({ phase: "error", message: err instanceof Error ? err.message : String(err) });
    }
  }

  function handleReset() {
    setConvState({ phase: "idle" });
    setSelectedNetwork(null);
    setSimMode("balanced");
    setStep(1);
  }

  return (
    <>
      <PageHeader
        title="OpenDSS → pandapower"
        description={step === 1
          ? "Select a network and simulation mode, then run the conversion pipeline."
          : "Choose a day and run the timeseries validation against OpenDSS."}
        actions={
          <Button
            variant="ghost" size="sm"
            onClick={step === 2 ? () => setStep(1) : onBack}
            className="gap-1 text-muted-foreground"
          >
            <ArrowLeft className="h-4 w-4" />
            {step === 2 ? "Back to conversion" : "All tools"}
          </Button>
        }
      />

      <StepIndicator current={step} />

      {/* ── Step 1 ── */}
      {step === 1 && (
        <>
          {convState.phase === "done" ? (
            <ConversionResult
              result={convState.result}
              onContinue={() => setStep(2)}
              onReset={handleReset}
            />
          ) : (
            <>
              {/* Network selection */}
              <div className="mb-6">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground mb-3">
                  1 — Select Network
                </h2>
                <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
                  {NETWORKS.map((net) => {
                    const isSelected = selectedNetwork === net.id;
                    return (
                      <button
                        key={net.id}
                        disabled={isConverting}
                        onClick={() => setSelectedNetwork(net.id)}
                        className={cn(
                          "text-left rounded-xl border p-4 transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                          isSelected ? "border-primary bg-primary/5 shadow-sm" : "border-border bg-card hover:border-primary/40 hover:bg-muted/30",
                          isConverting && "opacity-50 cursor-not-allowed",
                        )}
                      >
                        <div className="flex items-start justify-between mb-3">
                          <Badge variant={net.type === "Rural" ? "secondary" : "default"} className="text-[10px]">
                            {net.type}
                          </Badge>
                          {isSelected && <CheckCircle2 className="h-4 w-4 text-primary shrink-0" />}
                        </div>
                        <div className="font-semibold text-base mb-1">{net.name}</div>
                        <div className="flex items-center gap-1 text-xs text-muted-foreground mb-3">
                          <MapPin className="h-3 w-3 shrink-0" />{net.location}
                        </div>
                        <div className="space-y-1">
                          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                            <Scale className="h-3 w-3 shrink-0" />{net.voltage}
                          </div>
                          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                            <Layers3 className="h-3 w-3 shrink-0" />{net.topology}
                          </div>
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Simulation mode */}
              <div className="mb-8">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground mb-3">
                  2 — Simulation Mode
                </h2>
                <Card className="p-4">
                  <RadioGroup
                    value={simMode}
                    onValueChange={(v) => setSimMode(v as "balanced" | "unbalanced")}
                    className="grid grid-cols-1 sm:grid-cols-2 gap-3"
                    disabled={isConverting}
                  >
                    {SIM_MODES.map((mode) => (
                      <label
                        key={mode.id} htmlFor={mode.id}
                        className={cn(
                          "flex items-start gap-3 rounded-lg border p-4 cursor-pointer transition-all",
                          simMode === mode.id ? "border-primary bg-primary/5" : "border-border hover:border-primary/40 hover:bg-muted/30",
                          isConverting && "opacity-50 cursor-not-allowed",
                        )}
                      >
                        <RadioGroupItem value={mode.id} id={mode.id} className="mt-0.5 shrink-0" />
                        <div>
                          <div className="font-medium text-sm">{mode.label}</div>
                          <div className="text-xs text-muted-foreground mt-0.5">{mode.description}</div>
                        </div>
                      </label>
                    ))}
                  </RadioGroup>
                </Card>
              </div>

              {/* Error banner */}
              {convState.phase === "error" && (
                <div className="flex items-start gap-3 p-4 rounded-xl border border-destructive/30 bg-destructive/5 mb-6">
                  <AlertCircle className="h-4 w-4 text-destructive mt-0.5 shrink-0" />
                  <div>
                    <div className="text-sm font-medium text-destructive">Conversion failed</div>
                    <div className="text-xs text-muted-foreground mt-1 font-mono whitespace-pre-wrap break-all">
                      {convState.message}
                    </div>
                  </div>
                </div>
              )}

              {/* Action */}
              <div className="flex items-center justify-between border-t pt-5">
                <div className="text-sm text-muted-foreground">
                  {isConverting ? (
                    <span className="flex items-center gap-2">
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      Running pipeline — this may take a few minutes…
                    </span>
                  ) : canConvert ? (
                    <>Converting <span className="font-medium text-foreground">{selectedNet?.name}</span> in <span className="font-medium text-foreground">{simMode}</span> mode</>
                  ) : (
                    "Select a network to continue"
                  )}
                </div>
                <Button disabled={!canConvert || isConverting} onClick={handleConvert} className="gap-2">
                  {isConverting ? (
                    <><Loader2 className="h-4 w-4 animate-spin" /> Converting…</>
                  ) : (
                    <>Start Conversion <ArrowRight className="h-4 w-4" /></>
                  )}
                </Button>
              </div>
            </>
          )}
        </>
      )}

      {/* ── Step 2 ── */}
      {step === 2 && convState.phase === "done" && (
        <SimulationStep
          conversionResult={convState.result}
          onStepDone={() => {}}
        />
      )}
    </>
  );
}

// ── Page root ───────────────────────────────────────────────────────────────

function ConversionToolsPage() {
  const [activeTool, setActiveTool] = useState<ToolId | null>(null);

  return (
    <AppShell>
      {activeTool === null && <ToolLanding onSelect={setActiveTool} />}
      {activeTool === "opendss" && <OpenDSSFlow onBack={() => setActiveTool(null)} />}
    </AppShell>
  );
}
